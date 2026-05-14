import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import requests

from paths import CONTENT_QUALITY_LOG_PATH, DATA_DIR, OUTPUT_DIR
from similarity_checker import SimilarityChecker, save_similarity_report
from topic_registry import QA_USED_PATH

QUEUE_PATH = DATA_DIR / "writing_queue.csv"
TOP10_PATH = DATA_DIR / "topic_top10.csv"
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")


SIMILARITY_THRESHOLD = 0.52
STRUCTURAL_THRESHOLD = 0.60
SIMILARITY_REVIEW_THRESHOLD = 0.45
STRUCTURAL_REVIEW_THRESHOLD = 0.52
QUALITY_PENALTY_THRESHOLD = 70


def _get_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


MAX_REWRITE_ATTEMPTS = _get_int_env("BLOGAUTO_MAX_REWRITE_ATTEMPTS", 2)
API_MAX_ATTEMPTS = _get_int_env("BLOGAUTO_API_MAX_ATTEMPTS", 1)
API_TIMEOUT_SECONDS = _get_int_env("BLOGAUTO_API_TIMEOUT_SECONDS", 45)
MAX_TOPICS_PER_RUN = _get_int_env("BLOGAUTO_MAX_TOPICS_PER_RUN", 4)
ALLOW_DRAFTED_FALLBACK = _get_bool_env("BLOGAUTO_INCLUDE_DRAFTED_FALLBACK", False)
USE_API_ON_RETRY = _get_bool_env("BLOGAUTO_USE_API_ON_RETRY", False)
PARALLEL_WORKERS = _get_int_env("BLOGAUTO_PARALLEL_WORKERS", 1)
MIN_KOREAN_CONTENT_CHARS = _get_int_env("BLOGAUTO_MIN_KOREAN_CHARS", 2500, minimum=1000)
PIPELINE_VERIFY_RETRIES = _get_int_env("BLOGAUTO_PIPELINE_VERIFY_RETRIES", 2)
REQUIRED_SCENARIO_COUNT = 3
REQUIRED_QA_COUNT = 5
REQUIRED_SECTION_TITLES = [
    "서론",
    "본문 1: 개념 설명",
    "본문 2: 실무 적용 + 단계별 설명",
    "Q&A",
    "결론",
]

_state_lock = threading.Lock()


TOOL_PROFILES = [
    {
        "name": "excel_data",
        "tokens": ["엑셀", "excel", "시트", "피벗", "함수"],
        "surfaces": ["리본 메뉴", "데이터 탭", "수식 탭", "시트 영역", "이름 상자"],
        "workflow": "원본 표 정리, 기준 열 지정, 계산 결과 검증",
        "assets": ["원본 시트", "보조 열", "결과 시트", "검토용 샘플 행"],
        "pitfalls": ["열 범위가 흔들리는 문제", "텍스트와 숫자 형식이 섞이는 문제", "수식 복사 범위 오류"],
        "scenario_bank": [
            "월간 보고용 집계 표를 다시 쓰지 않도록 구조를 잡는 상황",
            "부서별 원본 데이터를 합치기 전에 기준 열을 정리하는 상황",
            "실수가 잦은 계산 과정을 검증용 열로 분리하는 상황",
            "조건부 서식이나 필터 결과를 팀 기준으로 맞추는 상황",
        ],
        "qa_bank": [
            "범위를 어디까지 잡아야 하나요?",
            "샘플 검증은 어떤 순서로 해야 하나요?",
            "다른 사람이 열어도 결과가 유지되게 하려면 어떻게 하나요?",
            "수정 전 백업은 어떤 형태가 좋나요?",
            "자동화 전에 꼭 확인할 열은 무엇인가요?",
            "함수 오류가 날 때 가장 먼저 확인해야 할 셀은 어디인가요?",
            "조건부 서식을 여러 열에 적용할 때 주의점은 무엇인가요?",
            "피벗 테이블이 업데이트되지 않을 때 어떻게 하나요?",
            "VLOOKUP 대신 INDEX/MATCH를 써야 하는 상황은 언제인가요?",
            "시트 보호와 잠금의 차이는 무엇인가요?",
            "데이터 유효성 검사를 설정할 때 기준은 어떻게 잡나요?",
            "인쇄 범위가 자꾸 밀릴 때 확인해야 할 설정은 무엇인가요?",
        ],
    },
    {
        "name": "word_docs",
        "tokens": ["워드", "word", "문서", "목차", "페이지 번호", "스타일"],
        "surfaces": ["리본 메뉴", "홈 탭", "삽입 탭", "참조 탭", "탐색 창"],
        "workflow": "문서 구조 정리, 스타일 통일, 출력 전 검토",
        "assets": ["원본 문서", "스타일 샘플", "검토본", "배포용 PDF"],
        "pitfalls": ["제목 스타일이 섞이는 문제", "페이지 레이아웃이 깨지는 문제", "자동 요소가 수동 수정과 충돌하는 문제"],
        "scenario_bank": [
            "보고서 초안을 표준 형식으로 정리해야 하는 상황",
            "긴 문서를 팀 공용 양식으로 재배치하는 상황",
            "자동 목차나 페이지 번호가 출력물에서 어긋나는 상황",
            "검토 의견을 반영하면서 본문 구조를 유지해야 하는 상황",
        ],
        "qa_bank": [
            "스타일은 언제 먼저 잡아야 하나요?",
            "페이지가 밀릴 때 어디부터 확인하나요?",
            "공유 전 어떤 보기 모드로 점검하는 게 좋나요?",
            "문단 서식과 글자 서식 충돌은 어떻게 줄이나요?",
            "자동 요소를 수동으로 건드리면 왜 문제가 생기나요?",
            "목차가 자동으로 업데이트되지 않을 때 원인은 무엇인가요?",
            "여러 사람이 편집할 때 추적 변경 기능은 어떻게 써야 하나요?",
            "각주와 미주 중 어떤 상황에 어떤 것을 쓰나요?",
            "그림이 텍스트와 함께 이동하게 설정하려면 어떻게 하나요?",
            "페이지 번호가 잘못된 숫자로 시작할 때 수정 방법은 무엇인가요?",
            "단락 간격과 줄 간격을 헷갈리지 않고 설정하는 방법은 무엇인가요?",
            "문서를 PDF로 저장할 때 서식이 깨지는 이유는 무엇인가요?",
        ],
    },
    {
        "name": "presentation_flow",
        "tokens": ["ppt", "powerpoint", "슬라이드", "프레젠테이션", "애니메이션"],
        "surfaces": ["슬라이드 축소판", "삽입 탭", "전환 탭", "애니메이션 창", "슬라이드 마스터"],
        "workflow": "메시지 흐름 정리, 장면 전환 통일, 발표 리허설 점검",
        "assets": ["원본 슬라이드", "마스터 레이아웃", "리허설 체크리스트", "발표본"],
        "pitfalls": ["효과가 과해지는 문제", "슬라이드 번호가 어긋나는 문제", "마스터와 개별 슬라이드가 충돌하는 문제"],
        "scenario_bank": [
            "발표 초안을 짧은 시간 안에 읽기 쉽게 다듬는 상황",
            "여러 사람이 만든 슬라이드를 한 톤으로 통일하는 상황",
            "애니메이션이나 전환 효과를 발표 흐름에 맞게 재배치하는 상황",
            "최종 발표 전에 모바일 화면과 프로젝터 환경을 함께 점검하는 상황",
        ],
        "qa_bank": [
            "애니메이션은 몇 단계까지가 적당한가요?",
            "슬라이드 번호가 안 맞을 때 어디부터 봐야 하나요?",
            "마스터를 먼저 수정해야 하나요, 개별 슬라이드를 먼저 수정해야 하나요?",
            "리허설 체크는 어떤 순서가 안전한가요?",
            "공유용과 발표용 파일을 따로 두는 이유는 무엇인가요?",
            "슬라이드마다 글꼴이 달라 보일 때 통일하는 방법은 무엇인가요?",
            "발표 중 영상이 재생되지 않을 때 사전 점검 방법은 무엇인가요?",
            "슬라이드 분량이 너무 많을 때 줄이는 기준은 무엇인가요?",
            "노트 페이지에는 어떤 내용을 넣는 게 좋나요?",
            "화면 전환 효과가 발표 흐름을 방해하는 경우는 언제인가요?",
            "팀 발표에서 각자 만든 슬라이드를 합칠 때 순서는 어떻게 되나요?",
            "외부 링크나 파일이 포함된 슬라이드를 공유할 때 주의점은 무엇인가요?",
        ],
    },
    {
        "name": "collaboration_system",
        "tokens": ["노션", "notion", "팀즈", "teams", "jira", "지라", "trello", "아사나"],
        "surfaces": ["왼쪽 사이드바", "데이터베이스 보기", "속성 패널", "자동화 규칙 화면", "공유 설정 창"],
        "workflow": "협업 흐름 정리, 담당자 기준 정의, 상태 전환 규칙 설계",
        "assets": ["공용 보드", "담당자 속성", "상태 필드", "회의용 보기"],
        "pitfalls": ["속성 이름이 제각각인 문제", "상태 규칙이 느슨한 문제", "권한 설정이 누락되는 문제"],
        "scenario_bank": [
            "개인 메모 수준의 페이지를 팀 운영 보드로 올려야 하는 상황",
            "상태 값과 담당자 기준을 맞춰 협업 병목을 줄이는 상황",
            "반복되는 보고 절차를 템플릿과 보기 설정으로 고정하는 상황",
            "자동화 규칙이 의도와 다르게 동작해 흐름을 다시 설계하는 상황",
        ],
        "qa_bank": [
            "상태 값은 몇 개로 시작하는 게 좋나요?",
            "공유 권한은 언제 분리해야 하나요?",
            "템플릿과 실제 운영 보드를 어떻게 나누나요?",
            "자동화 규칙은 어디까지 걸어두는 게 좋나요?",
            "초보 팀원이 들어와도 헷갈리지 않게 하려면 무엇을 고정해야 하나요?",
            "작업이 완료됐는데 담당자가 업데이트를 안 할 때 구조를 어떻게 바꾸나요?",
            "알림이 너무 많아 중요한 알림을 놓칠 때 설정은 어떻게 해야 하나요?",
            "보드 보기와 목록 보기 중 어떤 상황에 어떤 것을 쓰나요?",
            "회의록과 작업 카드를 연결할 때 어떤 기준으로 링크하나요?",
            "이전 프로젝트 데이터를 새 프로젝트에 재활용할 때 주의점은 무엇인가요?",
            "팀원이 갑자기 바뀔 때 인수인계를 빠르게 하려면 무엇을 미리 준비해야 하나요?",
            "여러 팀이 같은 도구를 쓸 때 공통 규칙은 어떻게 정하나요?",
        ],
    },
    {
        "name": "design_system",
        "tokens": ["피그마", "figma", "컴포넌트", "오토레이아웃", "프레임", "디자인"],
        "surfaces": ["레이어 패널", "상단 툴바", "오른쪽 속성 패널", "Assets 탭", "Prototype 패널"],
        "workflow": "레이아웃 구조화, 재사용 단위 설계, 리뷰 전달 기준 정리",
        "assets": ["프레임", "컴포넌트 세트", "스타일 토큰", "리뷰용 화면 캡처"],
        "pitfalls": ["컴포넌트 계층이 복잡해지는 문제", "오토레이아웃 제약이 꼬이는 문제", "로컬 스타일과 팀 라이브러리가 충돌하는 문제"],
        "scenario_bank": [
            "반복되는 UI 블록을 재사용 가능한 단위로 바꾸는 상황",
            "디자이너와 개발자가 같은 이름 체계를 쓰도록 정리하는 상황",
            "오토레이아웃이 길이 변화에 무너지지 않게 검증하는 상황",
            "프로토타입 전달 전에 상태별 화면을 정리하는 상황",
        ],
        "qa_bank": [
            "컴포넌트로 분리할 기준은 무엇인가요?",
            "오토레이아웃은 언제 오히려 독이 되나요?",
            "개발 전달용 이름 규칙은 어떻게 정하나요?",
            "팀 라이브러리 반영 전 무엇을 검토해야 하나요?",
            "리뷰 캡처를 남길 때 어떤 상태를 포함해야 하나요?",
            "컴포넌트를 수정했을 때 기존 인스턴스에 영향이 생기는 경우는 언제인가요?",
            "색상 토큰과 직접 컬러 지정은 어떻게 구분해 쓰나요?",
            "반응형 디자인을 피그마에서 테스트할 때 어떤 프레임 크기를 써야 하나요?",
            "디자인과 실제 개발 결과물이 다를 때 원인을 어디서 찾나요?",
            "아이콘을 컴포넌트로 만들 때 변형(variant)은 어떻게 설계하나요?",
            "팀원이 같은 컴포넌트를 각자 다르게 쓰고 있을 때 어떻게 정렬하나요?",
            "프로토타입 링크를 공유할 때 어떤 화면부터 시작해야 하나요?",
        ],
    },
    {
        "name": "game_dev",
        "tokens": ["유니티", "unity", "언리얼", "unreal", "블루프린트", "씬", "프리팹", "레벨"],
        "surfaces": ["Hierarchy", "Project 창", "Inspector", "Scene 뷰", "Blueprint Editor"],
        "workflow": "씬 구조 정리, 객체 재사용, 테스트 루프 단축",
        "assets": ["테스트 씬", "프리팹 또는 블루프린트", "검증용 오브젝트", "로그 기록"],
        "pitfalls": ["참조가 끊기는 문제", "씬별 설정이 달라지는 문제", "런타임 테스트와 에디터 설정이 엇갈리는 문제"],
        "scenario_bank": [
            "프로토타입에서 쓰던 임시 오브젝트를 재사용 구조로 바꾸는 상황",
            "씬 전환이나 레벨 로딩 흐름을 테스트 가능한 단위로 분리하는 상황",
            "팀원이 같은 프리팹 또는 블루프린트를 다르게 수정해 충돌이 나는 상황",
            "에디터에서는 되는데 빌드에서 달라 보이는 원인을 좁히는 상황",
        ],
        "qa_bank": [
            "테스트 씬은 왜 따로 두는 게 좋나요?",
            "프리팹과 개별 오브젝트 수정은 어떻게 구분하나요?",
            "씬 전환 오류가 날 때 어디부터 보나요?",
            "Inspector 기본값을 팀 기준으로 맞추려면 어떻게 하나요?",
            "문제가 생겼을 때 로그와 화면 중 무엇을 먼저 남겨야 하나요?",
            "에디터에서는 되는데 빌드에서 안 될 때 어디를 먼저 점검하나요?",
            "프레임 드롭이 생길 때 원인을 좁히는 순서는 어떻게 되나요?",
            "여러 씬에서 공통으로 쓰는 오브젝트를 관리하는 방법은 무엇인가요?",
            "버전 관리를 씬 파일에 적용할 때 충돌을 줄이는 방법은 무엇인가요?",
            "물리 충돌이 일정하지 않게 동작할 때 확인해야 할 설정은 무엇인가요?",
            "에셋 임포트 설정을 팀 기준으로 맞추는 방법은 무엇인가요?",
            "캐릭터 컨트롤러를 교체할 때 기존 애니메이션 연동은 어떻게 유지하나요?",
        ],
    },
    {
        "name": "ai_workflow",
        "tokens": ["chatgpt", "gpt", "클로드", "claude", "gemini", "perplexity", "ai", "프롬프트"],
        "surfaces": ["대화 입력창", "히스토리 목록", "모델 선택 영역", "소스 패널", "결과 복사 영역"],
        "workflow": "질문 구조 설계, 응답 검증, 재사용 가능한 프롬프트 정리",
        "assets": ["질문 템플릿", "검증 체크리스트", "예시 입력", "결과 기록 노트"],
        "pitfalls": ["질문 목적이 한 번에 너무 많이 섞이는 문제", "검증 없이 결과를 바로 쓰는 문제", "버전 차이를 기록하지 않는 문제"],
        "scenario_bank": [
            "한 번에 길게 묻던 질문을 단계별 작업 흐름으로 나누는 상황",
            "팀이 같은 프롬프트를 써도 결과 품질이 흔들리지 않게 표준화하는 상황",
            "출처나 근거가 필요한 답변을 검증 가능한 형태로 받는 상황",
            "실패한 프롬프트를 로그로 남기고 개선 포인트를 분리하는 상황",
        ],
        "qa_bank": [
            "질문을 몇 단계로 나누는 게 적당한가요?",
            "좋은 예시 입력은 어떻게 준비하나요?",
            "같은 질문인데 결과가 달라질 때 무엇을 기록해야 하나요?",
            "검증 체크리스트는 어디까지 상세해야 하나요?",
            "팀 공유용 프롬프트는 어떤 형식이 좋나요?",
            "AI 결과를 그대로 쓰면 안 되는 상황은 어떻게 판단하나요?",
            "긴 문서를 AI에게 요약시킬 때 정보 누락을 줄이는 방법은 무엇인가요?",
            "특정 도메인 지식이 필요한 작업에서 AI 신뢰도를 높이는 방법은 무엇인가요?",
            "AI가 출력한 코드나 수식에서 오류를 빠르게 잡는 방법은 무엇인가요?",
            "이전 대화 맥락을 다음 세션에서도 활용하려면 어떻게 해야 하나요?",
            "프롬프트를 팀이 함께 개선할 때 어떤 버전 관리 방식이 좋나요?",
            "AI 결과물의 저작권 문제는 어떤 기준으로 판단하나요?",
        ],
    },
]

DEFAULT_PROFILE = {
    "name": "general_practical",
    "tokens": [],
    "surfaces": ["상단 메뉴", "왼쪽 탐색 영역", "설정 창", "미리보기 영역", "검토 화면"],
    "workflow": "작업 준비, 기준 설정, 결과 검증",
    "assets": ["원본 자료", "복사본", "검토용 샘플", "최종본"],
    "pitfalls": ["기본값을 바로 적용하는 문제", "원본을 먼저 수정하는 문제", "검증 기록 없이 끝내는 문제"],
    "scenario_bank": [
        "처음 사용하는 기능을 실무 파일에 바로 넣기 전에 안전하게 테스트하는 상황",
        "반복 작업을 개인 요령이 아니라 절차로 바꾸는 상황",
        "오류 메시지가 모호해서 원인을 단계별로 좁혀야 하는 상황",
        "다른 사람에게 넘겨도 같은 결과가 나오게 기준을 정리하는 상황",
    ],
    "qa_bank": [
        "가장 먼저 백업해야 하는 이유는 무엇인가요?",
        "기본값을 그대로 쓰면 왜 문제가 생기나요?",
        "반복 작업을 절차로 남길 때 어떤 항목을 기록하나요?",
        "오류 재현은 왜 중요한가요?",
        "팀 공유 전 검토는 어디까지 해야 하나요?",
        "처음 배울 때 가장 많이 놓치는 설정은 무엇인가요?",
        "작업 순서를 잘못 잡으면 어떤 문제가 생기나요?",
        "다른 사람이 이어받아도 혼란이 없게 하려면 무엇을 남겨야 하나요?",
        "실수했을 때 되돌리는 방법은 어디까지 알아야 하나요?",
        "자동화를 도입하기 전에 반드시 점검해야 할 것은 무엇인가요?",
        "비슷해 보이는 두 가지 방법 중 더 안전한 것을 고르는 기준은 무엇인가요?",
        "결과물이 맞는지 확인하는 가장 빠른 방법은 무엇인가요?",
    ],
}

STRUCTURE_VARIANTS = [
    {
        "name": "problem_solution",
        "section_titles": [
            "문제 정의와 사용 시점",
            "핵심 원리와 판단 기준",
            "오류 상황별 대응 사례",
            "자주 막히는 질문",
            "정리와 확장 포인트",
        ],
        "section_focus": [
            "독자가 실제로 막히는 지점을 먼저 정의",
            "왜 이 기능이 필요한지보다 언제 써야 하는지를 강조",
            "문제 발생 전후의 차이를 보여 주는 예시 구성",
        ],
    },
    {
        "name": "workflow_playbook",
        "section_titles": [
            "흐름 설계 전 맥락 파악",
            "작업 흐름 설계",
            "단계별 실행 장면",
            "검토와 공유 기준",
            "자주 묻는 질문",
        ],
        "section_focus": [
            "준비 단계에서 무엇을 고정해야 하는지 설명",
            "실행 순서와 검토 순서를 분리",
            "개인 작업이 팀 흐름으로 이어지는 방식 강조",
        ],
    },
    {
        "name": "standardization_blueprint",
        "section_titles": [
            "반복 업무에서의 가치",
            "표준 절차 만들기",
            "표준화 적용 사례",
            "오류와 예외 처리",
            "자주 묻는 질문",
        ],
        "section_focus": [
            "반복 업무와 템플릿화 관점 강조",
            "팀 기준, 권한, 인수인계까지 확장",
            "예외 상황에서 절차를 어떻게 유지하는지 설명",
        ],
    },
    {
        "name": "decision_guide",
        "section_titles": [
            "언제 써야 하고 언제 멈춰야 하나",
            "선택 기준과 화면 해석",
            "상황별 판단 사례",
            "검증 체크리스트",
            "자주 묻는 질문",
        ],
        "section_focus": [
            "기능 남용을 막는 판단 기준 제공",
            "적용 범위와 해석 기준을 세분화",
            "검증 체크리스트를 강하게 강조",
        ],
    },
    {
        "name": "checklist_review",
        "section_titles": [
            "이것부터 확인하세요",
            "점검 항목 정리",
            "항목별 점검 실전",
            "실수 패턴과 예방 포인트",
            "자주 묻는 질문",
        ],
        "section_focus": [
            "사용자가 자주 건너뛰는 설정 항목을 구체적으로 제시",
            "각 항목이 없을 때 발생하는 결과를 먼저 설명",
            "체크 후에도 발생하는 실패 패턴까지 커버",
        ],
    },
    {
        "name": "comparison_guide",
        "section_titles": [
            "두 방식의 핵심 차이",
            "각각 유리한 상황",
            "직접 비교 장면",
            "선택 기준 한 줄 정리",
            "자주 묻는 질문",
        ],
        "section_focus": [
            "기능 나열 대신 상황별 판단 기준 중심",
            "어느 쪽이 무조건 낫다는 결론 배제",
            "같은 목적을 두 방식으로 처리하는 대조 장면 구성",
        ],
    },
    {
        "name": "quickstart_entry",
        "section_titles": [
            "왜 지금 시작해도 괜찮은가",
            "처음 5분 안에 할 것",
            "첫 번째 성공 장면",
            "초보가 자주 막히는 지점",
            "자주 묻는 질문",
        ],
        "section_focus": [
            "진입 장벽을 낮추는 첫인상 우선",
            "설치와 기본 설정 이후 첫 성공 경험 설계",
            "전문 용어 최소화, 한 단계씩 안내",
        ],
    },
]

STRUCTURE_BY_NAME = {variant["name"]: variant for variant in STRUCTURE_VARIANTS}

PROFILE_VARIANT_ORDER = {
    "excel_data": [
        "decision_guide",
        "checklist_review",
        "workflow_playbook",
        "comparison_guide",
        "problem_solution",
        "standardization_blueprint",
        "quickstart_entry",
    ],
    "word_docs": [
        "problem_solution",
        "checklist_review",
        "decision_guide",
        "quickstart_entry",
        "workflow_playbook",
        "comparison_guide",
        "standardization_blueprint",
    ],
    "presentation_flow": [
        "workflow_playbook",
        "checklist_review",
        "comparison_guide",
        "decision_guide",
        "problem_solution",
        "quickstart_entry",
        "standardization_blueprint",
    ],
    "collaboration_system": [
        "standardization_blueprint",
        "checklist_review",
        "workflow_playbook",
        "comparison_guide",
        "decision_guide",
        "problem_solution",
        "quickstart_entry",
    ],
    "design_system": [
        "workflow_playbook",
        "checklist_review",
        "comparison_guide",
        "problem_solution",
        "decision_guide",
        "quickstart_entry",
        "standardization_blueprint",
    ],
    "game_dev": [
        "problem_solution",
        "checklist_review",
        "workflow_playbook",
        "comparison_guide",
        "standardization_blueprint",
        "decision_guide",
        "quickstart_entry",
    ],
    "ai_workflow": [
        "decision_guide",
        "comparison_guide",
        "standardization_blueprint",
        "checklist_review",
        "workflow_playbook",
        "problem_solution",
        "quickstart_entry",
    ],
    "general_practical": [
        "workflow_playbook",
        "problem_solution",
        "checklist_review",
        "comparison_guide",
        "decision_guide",
        "quickstart_entry",
        "standardization_blueprint",
    ],
}

TOPIC_TYPE_VARIANT_PREFERENCES = {
    "error_solution": [
        "workflow_playbook",
        "problem_solution",
        "checklist_review",
        "decision_guide",
    ],
    "feature_explanation": [
        "quickstart_entry",
        "workflow_playbook",
        "decision_guide",
        "checklist_review",
    ],
    "practical_usage": [
        "workflow_playbook",
        "standardization_blueprint",
        "checklist_review",
        "decision_guide",
    ],
    "comparison_analysis": [
        "comparison_guide",
        "decision_guide",
        "workflow_playbook",
        "checklist_review",
    ],
}

TONE_PACKS = [
    {
        "name": "field_note",
        "hook": "What usually breaks first is not the feature, but the decision order around it.",
        "lens": "field-tested sequence",
        "review_label": "last-mile verification",
        "tip_label": "A practical field note",
        "risk_label": "silent failure",
    },
    {
        "name": "operator_brief",
        "hook": "A useful workflow becomes dangerous when the operator cannot explain why a setting was chosen.",
        "lens": "operator briefing",
        "review_label": "handoff readiness",
        "tip_label": "An operator habit",
        "risk_label": "handoff drift",
    },
    {
        "name": "checklist_mode",
        "hook": "The safest improvement often comes from shrinking the number of decisions made at once.",
        "lens": "checklist-first review",
        "review_label": "checkpoint review",
        "tip_label": "A checklist shortcut",
        "risk_label": "scope spill",
    },
    {
        "name": "coaching_mode",
        "hook": "Most teams do not need more features here; they need a clearer coaching path for the same feature.",
        "lens": "coaching-oriented explanation",
        "review_label": "team coaching check",
        "tip_label": "A coaching prompt",
        "risk_label": "unclear ownership",
    },
]

NARRATIVE_PACKS = [
    {
        "name": "diagnostic",
        "intro_close": "It reads the topic like a diagnosis of a working situation, not like a feature catalog.",
        "principle_close": "The main goal is to expose which decision should be fixed before more clicks are added.",
        "prep_close": "That keeps the first trial small enough to inspect without guesswork.",
        "reason_frame": "Locate the decision point in this scene — that is where the diagnosis actually lands.",
        "caution_frame": "The earliest warning usually appears before the final save.",
        "review_close": "This keeps the review anchored to evidence instead of memory.",
        "qa_close": "A short operating note matters more than a long explanation here.",
        "conclusion_close": "That is usually what separates a reusable method from a one-off success.",
    },
    {
        "name": "coaching",
        "intro_close": "Someone new to this topic should be able to follow the logic start to finish without asking for help.",
        "principle_close": "A principle worth keeping is one that holds when the owner changes, not just when conditions are perfect.",
        "prep_close": "Keeping setup small means the next person can verify it in under a minute.",
        "reason_frame": "Notice what this scene reveals about where judgment is actually required.",
        "caution_frame": "Handoff problems tend to show up as result problems — catching them early means catching them at the source.",
        "review_close": "A review note that someone else can pick up cold is more useful than one that requires memory.",
        "qa_close": "Leave behind a habit, not just an answer — the habit is what scales.",
        "conclusion_close": "A method that transfers cleanly is worth more than one that only works in the original hands.",
    },
    {
        "name": "audit",
        "intro_close": "Every claim in this article should be something a reviewer could verify independently.",
        "principle_close": "Principles that hold under review are worth more than those that only work under ideal conditions.",
        "prep_close": "Starting narrow creates a clean baseline — one that will hold up when the result is questioned later.",
        "reason_frame": "What this scene exposes is more valuable than the steps it describes.",
        "caution_frame": "A mismatch between intended scope and saved result is almost always the first place an audit surfaces a problem.",
        "review_close": "Good review notes outlast the screen — write them for someone who will never see the original state.",
        "qa_close": "Evidence that a choice was deliberate matters more than a perfect outcome.",
        "conclusion_close": "Outcomes that can be explained and reproduced are the only kind worth building on.",
    },
    {
        "name": "playbook",
        "intro_close": "The sequence is designed so each step sets up the next, not just completes itself.",
        "principle_close": "Keeping the sequence visible from preparation to review is what makes a playbook reusable.",
        "prep_close": "A focused first step limits the number of moving parts — that is the whole point of starting this way.",
        "reason_frame": "Pay attention to where the sequence bends here — that inflection point is the real lesson.",
        "caution_frame": "A broken sequence looks exactly like a broken button until you trace back one step.",
        "review_close": "That makes the workflow easier to repeat without rebuilding the logic each time.",
        "qa_close": "A useful answer here should preserve the sequence, not just the result.",
        "conclusion_close": "That is why the method keeps working even when the topic returns months later.",
    },
]

SCENARIO_PATTERNS = [
    {
        "name": "scope_first",
        "intro_label": "Scope-first scene",
        "step_label": "범위 기준 단계",
        "reason_label": "Why this scene matters",
        "caution_label": "Boundary caution",
    },
    {
        "name": "handoff_first",
        "intro_label": "Handoff-first scene",
        "step_label": "인수인계 기준 단계",
        "reason_label": "Why the handoff matters",
        "caution_label": "Ownership caution",
    },
    {
        "name": "review_first",
        "intro_label": "Review-first scene",
        "step_label": "검토 중심 단계",
        "reason_label": "Why the review order matters",
        "caution_label": "Review caution",
    },
    {
        "name": "rollback_first",
        "intro_label": "Rollback-first scene",
        "step_label": "되돌리기 기준 단계",
        "reason_label": "Why rollback readiness matters",
        "caution_label": "Recovery caution",
    },
]

SCENARIO_BLOCK_ORDERS = [
    {
        "name": "standard",
        "order": ["intro", "reason", "steps", "caution"],
    },
    {
        "name": "action_first",
        "order": ["intro", "steps", "reason", "caution"],
    },
    {
        "name": "risk_led",
        "order": ["intro", "caution", "steps", "reason"],
    },
    {
        "name": "evidence_led",
        "order": ["reason", "intro", "steps", "caution"],
    },
]

TITLE_VARIATIONS = {
    "problem_solution": [
        "{keyword} 왜 계속 안 되는가, 이 흐름을 먼저 확인하세요",
        "{keyword} 실무에서 자주 막히는 세 가지 상황",
        "{keyword} 오류 줄이는 순서, 이 지점부터 보세요",
        "{keyword} 이렇게 하면 안 됩니다",
    ],
    "workflow_playbook": [
        "{keyword} 시작 전에 정해야 할 것들",
        "{keyword} 실무에서 이 순서로 쓰면 됩니다",
        "{keyword} 준비부터 공유까지 한 번에 잡는 법",
        "{keyword} 매번 처음부터 하지 않는 방법",
    ],
    "standardization_blueprint": [
        "{keyword} 혼자만 알면 안 되는 이유",
        "{keyword} 팀에서 같은 결과를 내는 방법",
        "{keyword} 담당자가 바뀌어도 흔들리지 않는 구조",
        "{keyword} 한 번 만들어 두면 계속 쓰는 설정법",
    ],
    "decision_guide": [
        "{keyword} 언제 쓰고 언제 멈춰야 하나",
        "{keyword} 어떤 상황에서 어떤 방식을 써야 하는가",
        "{keyword} 선택 전에 확인해야 할 것",
        "{keyword} 잘못 쓰면 오히려 복잡해지는 이유",
    ],
    "checklist_review": [
        "{keyword} 시작 전 꼭 확인해야 할 것 정리",
        "{keyword} 놓치기 쉬운 설정, 체크리스트로 확인",
        "{keyword} 세팅할 때 빠뜨리면 나중에 고친다",
        "{keyword} 자꾸 오류 나는 이유가 여기 있습니다",
    ],
    "comparison_guide": [
        "{keyword} 두 가지 방식, 어떤 상황에서 뭘 쓰나",
        "{keyword} 방식 차이와 선택 기준",
        "{keyword} 같아 보이지만 다른 두 방법 비교",
        "{keyword} A와 B 중 어떤 게 나은가",
    ],
    "quickstart_entry": [
        "{keyword} 처음 쓰는 사람이 먼저 할 것",
        "{keyword} 설치 후 바로 해야 하는 5분 설정",
        "{keyword} 시작 전 알아야 할 것만 정리했습니다",
        "{keyword} 어렵지 않습니다, 이것부터 시작하세요",
    ],
}


INTRO_TEMPLATES = {
    "problem_solution": [
        (
            "{keyword}를 찾는 사람은 보통 정의가 아니라 막힌 지점을 해결하려고 합니다. "
            "특히 {surfaces}처럼 화면 선택지가 많은 도구에서는 어디서부터 눌러야 하는지보다 "
            "무엇을 먼저 고정해야 하는지가 더 중요합니다. 이 글은 {keyword}를 실제 작업 흐름 안에서 "
            "어느 시점에 꺼내야 하는지부터 설명하고, 실수 없이 적용하기 위한 기준을 잡는 데 초점을 둡니다.",
            "{hook} People searching for {keyword} usually need a fix, not a definition. "
            "In tools with many surfaces such as {surfaces}, the important question is not only where to click, "
            "but what must be fixed first. This guide starts from the moment when {keyword} becomes necessary "
            "and focuses on a {lens} that prevents avoidable mistakes.",
        ),
        (
            "같은 {keyword} 오류가 반복될 때, 원인은 보통 기능 자체가 아니라 적용 순서에 있습니다. "
            "{assets}처럼 기준이 되는 자료를 먼저 분리하지 않으면 변경 전후를 비교하기 어려워집니다. "
            "이 글은 오류가 나타나는 전형적인 세 가지 장면을 중심으로 어디서 기준을 고쳐야 하는지 설명합니다.",
            "{hook} When the same {keyword} issue keeps coming back, the cause is usually in the sequence, not the feature. "
            "Without first separating a reference such as {assets}, comparing before and after states becomes difficult. "
            "This guide explains three typical scenes where issues surface and exactly where to adjust the boundary using a {lens}.",
        ),
        (
            "{keyword}를 처음 건드릴 때 실수가 잦은 이유는 {surfaces}를 목적보다 먼저 열기 때문입니다. "
            "화면보다 목적과 범위를 먼저 정해 두면, 같은 단계를 다시 밟더라도 결과가 크게 달라집니다. "
            "이 글은 판단 순서를 장면별로 나눠 실패를 줄이는 방법을 설명합니다.",
            "{hook} Early mistakes with {keyword} often happen because {surfaces} is opened before the goal is defined. "
            "Setting the goal and scope before touching the screen changes outcomes significantly, even when the same steps are followed. "
            "This guide divides the judgment order into specific scenes through a {lens} to show where failure is most likely.",
        ),
        (
            "{keyword}가 왜 계속 안 될까요? 대부분의 경우 기능 자체는 정상인데 적용하는 순서가 틀립니다. "
            "{surfaces}에서 설정을 바꾸기 전에 {assets}부터 정리해야 하는 이유가 바로 여기 있습니다. "
            "이 글은 실패가 반복되는 패턴을 먼저 보여 주고, 어디서 방향을 바꿔야 하는지 역방향으로 짚어 줍니다.",
            "Why does {keyword} keep failing? In most cases the feature works fine — the sequence is wrong. "
            "That is why {assets} must be sorted before touching settings on {surfaces}. "
            "Rather than listing steps forward, this article traces back from failure patterns to show exactly where the sequence breaks, using a {lens}.",
        ),
        (
            "결론부터 말하면, {keyword} 문제의 80%는 첫 번째 단계에서 이미 결정됩니다. "
            "그 첫 단계에서 {surfaces}를 잘못 설정하거나 {assets}를 구분하지 않으면, 이후 모든 수정이 임시방편이 됩니다. "
            "이 글은 그 결정적인 첫 단계부터 시작해서, 왜 나머지가 그 방향으로 따라가야 하는지를 설명합니다.",
            "The short answer: 80% of {keyword} problems are decided at step one. "
            "If {surfaces} is misconfigured or {assets} is not separated at that point, every fix after that is a patch. "
            "This article starts from that decisive first step and explains why everything downstream depends on getting it right, through a {lens}.",
        ),
    ],
    "workflow_playbook": [
        (
            "{keyword}를 실무에 붙일 때는 기능 설명보다 작업 순서를 설계하는 편이 훨씬 도움이 됩니다. "
            "{workflow} 같은 흐름을 먼저 정리해 두면 화면 구성이 조금 달라도 길을 잃지 않습니다. "
            "이 글에서는 준비 단계, 실행 단계, 검토 단계를 분리해서 따라가기 쉬운 플레이북 형태로 정리하겠습니다.",
            "{hook} When applying {keyword} to practical work, designing the workflow is more useful than memorizing the feature description. "
            "If you map the flow around {workflow}, small screen differences become much less confusing. "
            "This article uses a playbook format that separates preparation, execution, and review through a {lens}.",
        ),
        (
            "실무에서 {keyword}를 처음 쓰는 사람이 막히는 지점은 대부분 기능이 아니라 순서입니다. "
            "{surfaces}처럼 화면이 많은 환경에서는 어떤 단계에서 어떤 화면을 열지 미리 정해 두는 것이 핵심입니다. "
            "이 글은 {assets}을 기준으로 실행 순서를 정리한 플레이북 형태로 이어집니다.",
            "{hook} For most people starting to use {keyword} at work, the barrier is sequence, not functionality. "
            "In environments with many surfaces such as {surfaces}, knowing which screen to open at each step in advance is the central challenge. "
            "This guide maps the execution order around {assets} through a {lens}.",
        ),
        (
            "{keyword} 관련 작업이 자꾸 반복되거나 오래 걸린다면, 기능보다 흐름을 먼저 고정하는 편이 빠릅니다. "
            "{assets}처럼 작업 자산을 기준으로 시작 조건을 정해 두면 매번 처음부터 판단하지 않아도 됩니다. "
            "이 글은 그 흐름을 준비, 실행, 검토 단계로 나눠 설명합니다.",
            "{hook} When {keyword} work keeps repeating or taking too long, anchoring the sequence beats learning more features. "
            "Defining starting conditions around assets such as {assets} removes the need to judge from scratch each time. "
            "This article breaks that sequence into preparation, execution, and review steps using a {lens}.",
        ),
        (
            "{keyword} 작업에서 가장 먼저 정해야 할 것은 무엇일까요? 기능이 아니라 '어디서 끝낼지'입니다. "
            "끝 지점을 먼저 정하면 {workflow} 과정에서 어느 화면을 건드려야 하는지 자연스럽게 좁혀집니다. "
            "이 글은 그 역방향 설계를 출발점으로 삼아 실무 흐름 전체를 조립합니다.",
            "For {keyword}, the first question is not where to start — it is where the work should end. "
            "Fixing the endpoint first naturally narrows which steps in {workflow} actually need attention. "
            "This article builds the full work sequence by starting from that endpoint and working backward through a {lens}.",
        ),
        (
            "{keyword}를 팀에서 쓰다 보면, 잘 됐던 흐름이 담당자가 바뀌고 나서 흔들리는 경우가 많습니다. "
            "이유는 절차가 아니라 맥락이 전달되지 않기 때문입니다. "
            "이 글은 {assets}을 기준으로 작업 맥락을 묶어 두는 방법을 중심으로 설명합니다.",
            "Teams using {keyword} often find that a smooth workflow breaks down after a handoff. "
            "The problem is not the steps — it is the context that goes unrecorded. "
            "This article centers on how to anchor that context around {assets} so the sequence holds regardless of who runs it, through a {lens}.",
        ),
    ],
    "standardization_blueprint": [
        (
            "{keyword}는 한 번 잘 쓰는 것보다 같은 결과를 반복해서 내는 것이 더 중요합니다. "
            "그래서 이 글은 {assets} 같은 작업 자산을 기준으로 반복 업무를 어떻게 표준화할지 설명합니다. "
            "개인 감각이 아니라 절차와 검토 포인트를 남겨 두면, 담당자가 바뀌어도 결과 품질이 흔들리지 않습니다.",
            "{hook} {keyword} matters more as a repeatable routine than as a one-time trick. "
            "This article explains how to standardize repeated work around assets such as {assets}. "
            "When the process and review points are documented, quality stays stable even if the owner changes under a {lens}.",
        ),
        (
            "한 사람만 쓸 줄 아는 방법은 팀 작업에서 오래가지 않습니다. "
            "{keyword}를 팀 단위로 운영하려면 {assets}처럼 작업 자산을 공용 기준으로 묶어야 합니다. "
            "이 글은 개인 작업 방식을 팀이 함께 쓸 수 있는 구조로 바꾸는 절차를 설명합니다.",
            "{hook} A method known only to one person does not hold up in team work. "
            "To operate {keyword} at a team level, assets such as {assets} must be tied to a shared standard. "
            "This guide walks through converting a personal approach into a shared structure using a {lens}.",
        ),
        (
            "{keyword}가 반복 업무에서 제대로 동작하려면 매번 기억에 의존하지 않아야 합니다. "
            "담당자가 바뀌어도 결과가 흔들리지 않으려면 {surfaces}와 {assets}에서 어떤 값을 고정할지 문서로 남겨야 합니다. "
            "이 글은 그 문서화 포인트를 실무 장면과 함께 설명합니다.",
            "{hook} For {keyword} to work reliably in repeated tasks, memory cannot be the anchor. "
            "When the owner changes, stable outcomes require documenting which values are fixed on {surfaces} and in {assets}. "
            "This article pairs those documentation points with real work scenes through a {lens}.",
        ),
        (
            "지금 {keyword} 작업이 잘 돌아가더라도, 그 방식이 다음 달에도 똑같이 재현될 수 있을지 물어보세요. "
            "대부분의 경우 '잘 된다'는 것과 '표준화됐다'는 것은 다릅니다. "
            "이 글은 그 간격을 좁히기 위해 {assets}을 중심으로 반복 가능한 기준을 만드는 방법을 설명합니다.",
            "Ask whether your current {keyword} approach could be reproduced exactly next month by a different person. "
            "'Working well' and 'standardized' are not the same thing. "
            "This article closes that gap by showing how to build a reproducible standard around {assets} through a {lens}.",
        ),
    ],
    "decision_guide": [
        (
            "{keyword}는 자주 쓰인다고 해서 항상 먼저 적용해야 하는 기능은 아닙니다. "
            "같은 화면에서도 적용 범위와 목적을 잘못 잡으면 시간이 줄어들기보다 오히려 복구 비용이 커질 수 있습니다. "
            "그래서 이 글은 언제 쓰고 언제 멈춰야 하는지, 어떤 기준으로 결과를 해석해야 하는지에 초점을 둡니다.",
            "{hook} {keyword} is not a feature that should be used first just because it is common. "
            "On the same screen, the wrong target range or goal can increase recovery cost instead of saving time. "
            "For that reason, this guide focuses on when to apply it, when to stop, and how to interpret the result through a {lens}.",
        ),
        (
            "{keyword}를 언제 써야 하는지보다 언제 쓰면 안 되는지 아는 것이 실제로 더 중요할 때가 있습니다. "
            "적용 범위를 넓게 잡으면 처리 속도가 빨라지는 것 같아도, 나중에 되돌려야 하는 경우가 오히려 많아집니다. "
            "이 글은 {keyword}를 안전하게 쓰기 위한 판단 기준을 실무 장면과 함께 정리합니다.",
            "{hook} Knowing when not to use {keyword} is sometimes more valuable than knowing when to use it. "
            "A wide target range may feel faster but often creates more cases that need to be undone later. "
            "This guide defines the judgment criteria for using {keyword} safely, illustrated with work scenes under a {lens}.",
        ),
        (
            "비슷해 보이는 상황에서 {keyword}를 쓸지 말지 헷갈린다면, 기준이 없는 것이 문제입니다. "
            "{surfaces}에서 어떤 값이 바뀌는지, {assets} 중 어디에 영향이 미치는지를 먼저 따져 두면 결정이 빨라집니다. "
            "이 글은 그 판단 기준을 장면별로 구체화합니다.",
            "{hook} When it is unclear whether to apply {keyword} in a situation that looks familiar, the missing piece is a clear criterion. "
            "Checking which values change on {surfaces} and which part of {assets} is affected makes the decision much faster. "
            "This guide turns those criteria into scene-specific guidelines using a {lens}.",
        ),
        (
            "{keyword}, 써야 할까요 말아야 할까요? 이 질문에 바로 답할 수 없다면, 판단 기준이 아직 없는 것입니다. "
            "상황마다 답이 다른 것처럼 느껴지지만, 실제로는 {surfaces}와 {assets} 두 가지만 확인하면 결정할 수 있습니다. "
            "이 글은 그 두 가지 기준을 실무 장면에 직접 대입해 설명합니다.",
            "Use {keyword} or not? If you cannot answer immediately, the missing piece is a decision framework, not more information. "
            "The answer varies by situation, but it almost always comes down to two checks: {surfaces} and {assets}. "
            "This article applies those two checks to real work scenes through a {lens} so the decision becomes faster.",
        ),
    ],
    "checklist_review": [
        (
            "{keyword}를 쓰다 보면 당연히 됐을 거라 생각했는데 나중에 확인해 보니 빠져 있던 항목들이 있습니다. "
            "이런 항목들은 처음부터 목록으로 정해 두지 않으면 바쁠 때 건너뛰기 쉽습니다. "
            "이 글은 {keyword} 사용 전 꼭 확인해야 할 항목을 정리하고, 각 항목을 놓쳤을 때 어떤 문제가 생기는지 함께 설명합니다.",
            "{hook} With {keyword}, items that seem obvious often turn out to be missing when you check later. "
            "Without a fixed list, it is easy to skip them when things get busy. "
            "This article organizes the key items to verify before using {keyword} and explains what goes wrong when each one is missed, from a {lens}.",
        ),
        (
            "{keyword}를 처음 셋업하거나 다시 점검할 때 어디서부터 시작해야 할지 막막한 경우가 많습니다. "
            "이 글은 그 막막함을 줄이기 위해 확인 항목을 순서대로 정리하고, 각 항목이 왜 필요한지 이유와 함께 설명합니다. "
            "{surfaces}에서 놓치기 쉬운 설정과 {assets} 기준으로 점검해야 할 포인트가 핵심입니다.",
            "{hook} Whether setting up {keyword} for the first time or reviewing an existing setup, knowing where to start is often the hardest part. "
            "This article removes that uncertainty by listing verification items in order and explaining the reason behind each one using a {lens}. "
            "The focus is on easy-to-miss settings on {surfaces} and checkpoints anchored to {assets}.",
        ),
        (
            "{keyword} 설정을 다 마쳤는데도 문제가 생겼다면, 체크리스트의 어느 항목이 빠진 것입니다. "
            "문제는 항상 '빠진 항목'이 있는 게 아니라, '빠진 줄 몰랐던 항목'이 있다는 데 있습니다. "
            "이 글은 그런 항목들을 {surfaces}와 {assets} 기준으로 정리하고, 각각 놓치면 어떤 일이 생기는지 먼저 보여 줍니다.",
            "If {keyword} is set up but something still goes wrong, a checklist item was skipped — probably one you did not know to check. "
            "The problem is never 'there is a missing step.' It is 'there was a step no one thought to list.' "
            "This article surfaces those invisible items by anchoring to {surfaces} and {assets}, and shows the consequence of each gap first, through a {lens}.",
        ),
        (
            "{keyword}의 점검 항목을 처음 만드는 사람이 가장 많이 하는 실수는 '되는 경우'를 기준으로 목록을 짜는 것입니다. "
            "실제로 필요한 목록은 '안 됐을 때 무엇을 확인했는가'를 기반으로 만들어야 합니다. "
            "이 글은 그 반대 방향, 즉 실패 기록을 기준으로 체크리스트를 만드는 방법을 설명합니다.",
            "The most common mistake when building a {keyword} checklist is writing it based on what worked. "
            "An effective checklist is built from the opposite: what was checked when things failed. "
            "This article takes that failure-first direction and shows how to build a durable checklist from {assets} outward, through a {lens}.",
        ),
    ],
    "comparison_guide": [
        (
            "{keyword}에는 비슷해 보이지만 사용 상황이 다른 두 가지 방식이 있습니다. "
            "어느 쪽이 무조건 낫다는 답은 없고, 어떤 상황인지에 따라 선택이 달라집니다. "
            "이 글은 두 방식의 실질적인 차이를 정리하고, 각각 어떤 상황에서 더 잘 맞는지 설명합니다.",
            "{hook} {keyword} has two approaches that look similar but work differently in practice. "
            "Neither is unconditionally better — the right choice depends on the situation. "
            "This article clarifies the practical differences and explains which context fits each approach through a {lens}.",
        ),
        (
            "{keyword}를 두고 어떤 방법을 써야 할지 고민되는 상황은 생각보다 자주 옵니다. "
            "{surfaces}처럼 선택지가 여럿인 환경에서는 기능만 보면 판단이 어려워집니다. "
            "이 글은 상황을 기준으로 두 방식을 비교하고, 각각 언제 쓰는 게 적합한지 기준을 제시합니다.",
            "{hook} Deciding which approach to use for {keyword} comes up more often than expected. "
            "In environments with multiple options like {surfaces}, function alone makes the decision hard. "
            "This article compares the two approaches by situation and offers criteria for when each one fits using a {lens}.",
        ),
        (
            "A 방법과 B 방법, 둘 다 {keyword}에서 쓸 수 있다는 걸 알고 있었나요? "
            "대부분은 하나만 쓰다가 막히고 나서야 다른 방법이 있다는 걸 알게 됩니다. "
            "이 글은 두 방법이 각각 어떤 상황에서 더 잘 맞는지를 {surfaces}와 {assets}를 기준으로 비교합니다.",
            "Did you know {keyword} can be approached two different ways? "
            "Most people discover the second method only after the first one fails. "
            "This article compares both against real situations using {surfaces} and {assets} as the measuring stick, through a {lens}.",
        ),
        (
            "{keyword}에서 방법 A와 방법 B 중 하나를 선택해야 한다면, 지금 당장 어느 쪽을 쓰겠습니까? "
            "이 질문에 바로 답할 수 없다면, 이 글이 그 판단 기준을 만들어 드립니다. "
            "두 방식의 차이를 실무 장면에 직접 대입해 비교하는 방식으로 설명합니다.",
            "If you had to choose between method A and method B for {keyword} right now, which would you pick? "
            "If the answer is not immediate, this article builds the criteria that make it so. "
            "It maps the difference between the two directly onto real work scenes through a {lens}, so the choice becomes clear.",
        ),
    ],
    "quickstart_entry": [
        (
            "{keyword}를 처음 써보려는 분들이 가장 많이 하는 실수는 너무 많은 것을 한꺼번에 시작하려는 것입니다. "
            "처음에는 전체 기능을 알 필요 없이, 딱 하나의 성공 경험만 만들면 됩니다. "
            "이 글은 {keyword}를 처음 쓰는 사람이 5분 안에 첫 결과를 내는 방법을 중심으로 설명합니다.",
            "{hook} The most common mistake for people starting with {keyword} is trying to begin everything at once. "
            "At first, the goal is not to understand all features — it is only to create one small success. "
            "This article focuses on how a first-time user can get a real result within five minutes using a {lens}.",
        ),
        (
            "{keyword}를 처음 접하면 화면은 많고 어디서부터 시작해야 할지 보이지 않습니다. "
            "이 글은 그 혼란을 줄이기 위해 처음에 꼭 해야 하는 것만 순서대로 정리했습니다. "
            "나머지 기능은 첫 번째 성공 이후에 배워도 충분합니다.",
            "{hook} When first opening {keyword}, the screen looks full and the starting point is not obvious. "
            "This article reduces that confusion by presenting only what must be done first, in order. "
            "The rest of the features can be learned after the first small success using a {lens}.",
        ),
        (
            "{keyword}, 5분이면 시작할 수 있습니다. "
            "처음에 {surfaces}에서 딱 하나의 항목만 설정하면 첫 번째 결과를 바로 볼 수 있습니다. "
            "이 글은 그 하나의 항목부터 시작해서 자연스럽게 다음 단계로 이어지도록 설명합니다.",
            "{keyword} takes five minutes to start — really. "
            "Set one item on {surfaces} and you will see the first result immediately. "
            "This article starts from that one item and walks forward from there through a {lens}, so the next step always feels reachable.",
        ),
        (
            "{keyword}를 배우기 전에 딱 한 가지만 물어보세요: '지금 당장 써야 하는 상황이 있나요?' "
            "있다면 이 글이 딱 맞습니다. {assets}을 하나 준비해서 바로 시작하는 방법을 중심으로 설명하기 때문입니다. "
            "이론보다 첫 실행 경험이 훨씬 빠른 이해를 만들어 줍니다.",
            "Before learning {keyword}, ask one question: is there a situation where you need it right now? "
            "If yes, this article is the right starting point — it centers on beginning immediately with one {assets} in hand. "
            "A first hands-on run teaches more than theory, and this guide is built around that premise through a {lens}.",
        ),
    ],
}

QA_ANSWER_TEMPLATES = [
    {
        "ko": (
            "핵심은 {surface}에서 바꾸는 값과 {asset}의 역할을 분리해 보는 것입니다. "
            "실행 방법은 먼저 복사본에서 한 항목만 조정하고, 결과를 기준 샘플과 비교한 뒤 적용 범위를 확정하는 것입니다. "
            "주의할 점은 {pitfall}를 피하려고 여러 옵션을 동시에 바꾸면 오히려 원인 추적이 어려워진다는 점입니다. "
            "실전 팁은 작업 메모에 화면 이름, 선택 범위, 저장 위치를 한 줄로 남겨 두는 것입니다."
        ),
        "en": (
            "The key is to separate the value changed on {surface} from the role of {asset}. "
            "The practical approach is to adjust one item in a copied file, compare the result with a baseline sample, and only then finalize the target scope. "
            "Be careful, because changing many options at once to avoid {pitfall} makes root-cause tracing much harder. "
            "{tip_label}: leave one short note with the screen name, selected scope, and save location. {qa_close}"
        ),
    },
    {
        "ko": (
            "출발점은 {surface}에서 현재 값이 어떤 상태인지 기록해 두는 것입니다. "
            "그런 다음 {asset}만 복제해서 한 가지 변경을 적용한 뒤 기대 결과와 비교하세요. "
            "{pitfall} 쪽으로 번질 가능성이 있다면, 적용 범위를 먼저 반으로 줄여 시험하는 것이 낫습니다. "
            "작업 중에는 '변경 전 상태 - 적용 범위 - 확인 결과' 순서로 메모를 남겨 두면 추후 설명이 편합니다."
        ),
        "en": (
            "Start by recording the current state of values on {surface} before touching anything. "
            "Then duplicate {asset}, apply one change, and compare the outcome against what you expected. "
            "If there is risk of drifting toward {pitfall}, halving the target scope for the trial run is the safer choice. "
            "{tip_label}: keep a short note in this order: state before change, target scope, confirmed result. {qa_close}"
        ),
    },
    {
        "ko": (
            "실무에서는 {asset}과 {surface}를 먼저 열어 두고 어디에 영향이 미칠지 경로를 먼저 따져 보는 게 순서입니다. "
            "한 번에 모든 옵션을 끝내려 하지 말고, 가장 작은 단위로 나눠 결과를 확인한 뒤 범위를 늘리세요. "
            "{pitfall}은 대개 첫 번째 적용 단계에서 발생하므로, 첫 변경 직후 검토 시간을 꼭 확보하세요. "
            "화면 이름과 선택 항목만 메모해도 나중에 재현하거나 팀원에게 설명할 때 충분한 근거가 됩니다."
        ),
        "en": (
            "In real work, open {asset} and {surface} first, then trace which paths will be affected before changing anything. "
            "Break the task into the smallest unit, confirm the result, then expand the scope instead of finishing everything at once. "
            "Since {pitfall} typically starts in the very first step, always build in review time immediately after the first change. "
            "{tip_label}: a note with just the screen name and selected items is enough to replay the process or explain it to a teammate later. {qa_close}"
        ),
    },
]

CONCLUSION_TEMPLATES = [
    {
        "ko": (
            "{keyword}를 잘 쓴다는 것은 기능 이름을 외우는 일이 아니라, "
            "어떤 화면에서 어떤 값을 고정해야 결과가 흔들리지 않는지 아는 일에 가깝습니다. "
            "오늘 정리한 방식처럼 작업 자산을 분리하고, 실무 장면별 기준을 따로 두고, "
            "검토 기록까지 남겨 두면 같은 주제를 다시 다뤄도 글과 작업 절차가 훨씬 선명해집니다."
        ),
        "en": (
            "Using {keyword} well is less about memorizing a feature name and more about knowing which values on which screens must stay fixed for stable results. "
            "When the work assets are separated, the criteria are split by scenario, and review notes are kept, "
            "both the article and the practical procedure stay much clearer even when the topic returns later. "
            "That is the durable outcome of a {lens}. {conclusion_close}"
        ),
    },
    {
        "ko": (
            "{keyword}를 실무에서 안정적으로 쓰는 사람은 기능을 많이 알기보다 언제 쓸지 판단하는 기준이 선명한 편입니다. "
            "이 글에서 다룬 세 가지 장면처럼, 작업 전 기준을 정해 두고 검토 기록을 남기는 습관이 쌓이면 다음 작업도 훨씬 빠릅니다."
        ),
        "en": (
            "People who use {keyword} reliably at work tend to have clearer criteria for when to apply it rather than more knowledge of features. "
            "As the three scenes in this article show, the habit of setting criteria before starting and keeping review records makes the next task significantly faster. "
            "That is how a {lens} stays useful over repeated cycles. {conclusion_close}"
        ),
    },
    {
        "ko": (
            "{keyword}에서 가장 많은 시간을 낭비하는 지점은 실행 중이 아니라 실행 전 기준을 정하지 않은 데서 시작합니다. "
            "이 글에서 정리한 절차와 검토 포인트를 한 번이라도 직접 써 보면, 이후 비슷한 작업에서 결정 속도가 눈에 띄게 달라집니다."
        ),
        "en": (
            "The biggest time drain in {keyword} work starts not during execution but when criteria are left undefined beforehand. "
            "Running through the procedure and review points in this article even once will noticeably accelerate decisions in similar tasks going forward. "
            "That shift is the real value of building a {lens} around this kind of work. {conclusion_close}"
        ),
    },
]

PROFILE_PRINCIPLES_ANGLE = {
    "excel_data": 0,
    "word_docs": 0,
    "presentation_flow": 1,
    "collaboration_system": 1,
    "design_system": 2,
    "game_dev": 1,
    "ai_workflow": 2,
    "general_practical": 0,
}

PRINCIPLES_BODIES = [
    {
        "ko": (
            "{keyword}를 처음 다루는 사람이 가장 먼저 해야 할 일은 기능을 켜는 것이 아니라 '판단 기준'을 세우는 것입니다. "
            "판단 기준이란 '이 작업을 어디까지 바꿀 것인가', '결과가 어떤 상태여야 완료로 볼 것인가'를 미리 정해 두는 것입니다. "
            "이 기준이 없으면 {surfaces}를 열었을 때 어떤 옵션을 눌러야 하는지 막막해지고, 클릭을 반복하다가 의도하지 않은 변경이 생기기 쉽습니다. "
            "{focus_text} 같은 관점을 미리 정리해 두면 화면에서 시선이 분산되지 않고 필요한 항목만 빠르게 찾을 수 있게 됩니다. "
            "반대로 기준 없이 바로 적용하면 {pitfalls} 같은 문제가 작업 도중이나 작업 직후에 드러납니다. "
            "이런 문제는 대부분 되돌리는 데 시간이 더 걸리기 때문에, 처음 5분을 기준 설정에 쓰는 것이 전체 작업 시간을 줄이는 가장 확실한 방법입니다."
        ),
        "en": (
            "The first thing someone new to {keyword} should do is not enable the feature, but establish a decision baseline. "
            "A decision baseline means defining in advance how far the work will go and what state counts as done. "
            "Without it, opening {surfaces} feels overwhelming, and repeated clicking often causes unintended changes. "
            "Organizing the viewpoint around points such as {focus_text} keeps attention focused and makes the right items easy to find quickly. "
            "Without that baseline, issues such as {pitfalls} tend to surface mid-task or right after, and undoing them usually takes longer than the original task. "
            "Spending the first five minutes on a clear baseline is the most reliable way to reduce total work time — that is the essence of {risk_label}."
        ),
    },
    {
        "ko": (
            "{pitfalls}처럼 같은 문제가 반복된다면, 가장 먼저 확인해야 할 것은 기능이 아니라 '작업 순서'입니다. "
            "많은 경우 기능 자체는 제대로 동작하고 있는데, 어떤 단계에서 어떤 화면을 먼저 열었느냐가 결과를 결정합니다. "
            "예를 들어 {surfaces} 중 설정 화면을 기준 화면보다 먼저 열면, 기준이 없는 상태에서 값을 바꾸게 되어 나중에 어떤 값이 올바른지 알 수 없게 됩니다. "
            "{keyword}를 적용하기 전에 {surfaces}에서 현재 상태가 어떤지 먼저 기록해 두는 습관이 이 순서 문제를 막아 줍니다. "
            "{focus_text}처럼 문제가 생기기 쉬운 지점을 미리 알고 있으면, 같은 화면을 보더라도 어디서 멈춰야 하는지 판단이 훨씬 빨라집니다. "
            "처음에는 이 기록 습관이 번거롭게 느껴질 수 있지만, 작업이 쌓일수록 오류 원인을 찾는 시간이 눈에 띄게 줄어드는 것을 확인할 수 있습니다."
        ),
        "en": (
            "When the same issues such as {pitfalls} keep coming back, the first thing to check is the work sequence, not the feature. "
            "In most cases the feature works correctly, but which screen was opened first at which step is what determines the outcome. "
            "For example, opening a settings screen among {surfaces} before a reference screen means changing values without a baseline, making it impossible to know later which value was correct. "
            "Building a habit of recording the current state on {surfaces} before applying {keyword} prevents this sequencing problem. "
            "Knowing in advance which points are prone to failure, as in {focus_text}, makes it much faster to judge where to stop even when looking at the same screen. "
            "This recording habit may feel tedious at first, but as tasks accumulate, the time spent tracing errors decreases noticeably — that is the core of {risk_label} prevention."
        ),
    },
    {
        "ko": (
            "{keyword}를 처음 접할 때 가장 많이 놓치는 것은 '적용 범위'입니다. "
            "적용 범위란 이 기능이 어디까지 영향을 미치는지, 즉 어떤 파일, 어떤 시트, 어떤 항목이 바뀌는지를 말합니다. "
            "범위를 미리 정하지 않으면 의도한 것보다 넓게 적용되거나, 반대로 필요한 부분에만 적용되지 않아서 결과를 보고 당황하게 됩니다. "
            "{focus_text}처럼 작업의 목적과 범위를 먼저 한 줄로 정리해 두면, {surfaces}를 열었을 때 어떤 옵션을 건드려야 할지가 자연스럽게 좁혀집니다. "
            "범위를 흐릿하게 잡은 채로 진행하면 {pitfalls} 문제로 이어질 가능성이 높고, 수정 후에도 결과가 기대와 다를 때 원인을 찾기 어렵습니다. "
            "처음 시작할 때는 '이 작업에서 바꿔야 하는 것'과 '바꾸면 안 되는 것'을 구분하는 것부터 시작하면, 범위 설정이 훨씬 쉬워집니다."
        ),
        "en": (
            "The most commonly missed element when first approaching {keyword} is the scope — meaning which files, sheets, or items will actually change. "
            "Without defining scope in advance, the feature often applies more broadly than intended, or misses the needed area entirely, leading to surprise when the result appears. "
            "Writing the goal and scope in one line first, as in {focus_text}, naturally narrows which options on {surfaces} need to be touched. "
            "Proceeding with a blurry scope almost always leads to {pitfalls} showing up, and when the result differs from expectations, the cause becomes hard to trace. "
            "A practical starting point: separate 'what must change in this task' from 'what must not change' before opening any screen. "
            "That simple split makes scope-setting much more concrete and is the foundation of solid {risk_label} practice."
        ),
    },
]

PRINCIPLES_ASSET_NOTES = [
    {
        "ko": (
            "실무에서 가장 자주 발생하는 실수 중 하나는 원본 파일에 직접 변경을 가하는 것입니다. "
            "처음에는 빠르게 끝낼 수 있을 것 같지만, 결과가 예상과 다를 때 되돌릴 기준이 없어서 처음부터 다시 시작해야 하는 상황이 생깁니다. "
            "{assets}처럼 작업 자산을 원본, 작업 복사본, 검토용 샘플로 미리 분리해 두면 변경 전후를 언제든지 비교할 수 있습니다. "
            "복사본에서 작업하다가 결과가 잘못되면 원본을 다시 복사하면 그만이기 때문에, 심리적 부담 없이 다양한 방법을 시험해볼 수 있습니다. "
            "또한 다른 팀원에게 작업 내용을 전달할 때도, '이 파일은 원본이고, 이 파일은 수정본입니다'라고 명확히 구분할 수 있어 인수인계가 훨씬 매끄러워집니다."
        ),
        "en": (
            "One of the most common mistakes in practical work is applying changes directly to the original file. "
            "It may seem faster at first, but when the result differs from expectations, there is no reference to revert to, forcing a restart from scratch. "
            "Separating assets such as {assets} into source, working copy, and review sample in advance means you can compare before and after states at any time. "
            "If a working copy goes wrong, simply copy the original again — this removes the psychological pressure and makes it safe to try different approaches. "
            "It also makes handoff much smoother: you can clearly say 'this is the original and this is the modified version' without ambiguity."
        ),
    },
    {
        "ko": (
            "팀 안에서 {keyword}를 일관되게 쓰려면 {assets}의 이름과 역할부터 공통 기준으로 맞춰야 합니다. "
            "혼자 쓸 때는 파일 이름이나 폴더 구조가 달라도 본인이 기억하면 되지만, 팀 작업에서는 다른 사람이 같은 파일을 열었을 때 즉시 역할을 파악할 수 있어야 합니다. "
            "예를 들어 '최종본', '최최종', '진짜최종' 같은 이름이 생기는 이유는 처음부터 이름 규칙을 정하지 않았기 때문입니다. "
            "작업을 시작하기 전에 '원본은 _original, 작업 중인 것은 _draft, 검토 완료된 것은 _final'처럼 이름 규칙 하나만 정해 두면 혼란이 크게 줄어듭니다. "
            "인수인계할 때도 이름만 보고 어떤 파일이 기준인지 바로 알 수 있어 검토 시간이 줄고 실수 가능성도 낮아집니다."
        ),
        "en": (
            "To use {keyword} consistently across a team, the name and role of assets such as {assets} must be aligned to a shared standard first. "
            "Working alone, you can remember different file names and folder structures yourself, but in team work, anyone opening the file must immediately understand its role. "
            "Files named 'final', 'final2', 'actual_final' exist precisely because no naming rule was defined at the start. "
            "Agreeing on a simple convention before starting — such as _original for source, _draft for work in progress, _final for reviewed output — dramatically reduces confusion. "
            "During handoff, the file name alone communicates which version is the baseline, shortening review time and reducing the chance of mistakes."
        ),
    },
    {
        "ko": (
            "{assets}를 변경 전후 기준으로 명확히 분리해 두면, 나중에 '왜 이렇게 바꿨는지'를 빠르게 설명할 수 있습니다. "
            "특히 같은 파일을 여러 차례 수정하는 과정에서는, 어떤 시점의 버전이 기준이었는지 추적할 수 있어야 오류가 생겼을 때 복구 범위를 최소화할 수 있습니다. "
            "버전을 분리하지 않으면 오류가 발생했을 때 '어디서부터 잘못됐는지'를 찾는 데만 시간이 몇 배로 걸릴 수 있습니다. "
            "간단한 방법은 작업할 때마다 날짜나 번호를 파일 이름에 붙이는 것입니다. 예를 들어 'report_0513_v1', 'report_0513_v2'처럼 관리하면 되돌아갈 지점이 명확해집니다. "
            "이 습관은 혼자 작업할 때도 유용하지만, 팀 작업이나 장기 프로젝트에서 특히 빛을 발합니다."
        ),
        "en": (
            "When assets such as {assets} are clearly split into before and after states, explaining 'why this change was made' later becomes very fast. "
            "In processes where the same file is revised multiple times, being able to trace which version was the baseline at any point limits how much needs to be recovered when something goes wrong. "
            "Without version separation, finding 'where things went wrong' after an error can take several times longer than the fix itself. "
            "A simple approach: append a date or number to the file name each time you work — for example, report_0513_v1, report_0513_v2. This makes the revert point obvious. "
            "This habit is useful even for solo work, but becomes especially powerful in team projects or long-running tasks."
        ),
    },
]

PREPARATION_BODIES = [
    {
        "ko": (
            "시작 전에 준비해야 할 것이 있습니다. 먼저 {assets}를 원본과 작업용 복사본으로 나눠 두세요. "
            "처음 시도할 때는 원본이 바뀌면 안 되기 때문에, 복사본을 만들어 두는 것이 가장 기본적인 안전장치입니다. "
            "다음으로 {surfaces} 중 어느 화면에서 기준 값을 확인하고 바꿀지 순서를 정해야 합니다. "
            "화면을 무작위로 열다 보면 어디서 어떤 값을 바꿨는지 기억하기 어려워집니다. "
            "{keyword}를 바로 실파일에 적용하지 말고, 복사본이나 테스트 화면에서 한 번 결과를 확인한 뒤에 실파일에 옮기는 순서를 지키세요. "
            "특히 기본값이 자동으로 채워지는 도구일수록 현재 선택 범위와 저장 대상이 의도한 대로 맞춰져 있는지 반드시 먼저 확인해야 합니다. "
            "이 준비 단계를 건너뛰면 나중에 문제가 생겼을 때 어디서부터 잘못됐는지 찾는 데 훨씬 많은 시간이 걸립니다."
        ),
        "en": (
            "There are a few things to prepare before starting. First, split {assets} into an original and a working copy. "
            "On a first attempt, the original must not change, so creating a copy is the most basic safety measure. "
            "Next, decide the order in which you will check and change values across {surfaces}. "
            "Opening screens at random makes it very hard to remember which value was changed where. "
            "Do not apply {keyword} to the live file immediately; check the result on a copy or test screen first, then transfer it to the live file. "
            "This matters most in tools that prefill defaults, because the selected scope and save target can silently drift. "
            "Skipping this preparation stage means that when something goes wrong, tracing where it started takes significantly longer — that is the core risk this {lens} is designed to prevent."
        ),
    },
    {
        "ko": (
            "준비 단계에서 가장 중요한 원칙은 '가장 작은 변경부터 시작한다'는 것입니다. "
            "처음부터 모든 설정을 한꺼번에 바꾸려고 하면, 결과가 예상과 다를 때 어떤 변경이 문제를 일으켰는지 알 수 없게 됩니다. "
            "{assets} 중 하나를 복제해서 {surfaces}에서 옵션 하나만 바꿔 보고, 그 결과가 기대한 방향으로 바뀌었는지 확인하세요. "
            "한 가지 변경이 확인됐으면 그다음 변경으로 넘어가는 방식으로 단계를 밟으면, 어느 설정이 어떤 결과를 만드는지 체계적으로 파악할 수 있습니다. "
            "이 첫 번째 시험이 실패해도 원본에는 전혀 영향이 없기 때문에, 부담 없이 여러 방법을 시험해볼 수 있습니다. "
            "초보자일수록 이 '하나씩 확인하는 습관'이 결과적으로 가장 빠른 길이 됩니다."
        ),
        "en": (
            "The most important principle in the preparation stage is to start with the smallest possible change. "
            "Trying to change all settings at once means that when the result differs from expectations, it becomes impossible to tell which change caused the problem. "
            "Duplicate one of the {assets}, change a single option on {surfaces}, and confirm whether the result moved in the expected direction. "
            "Once one change is verified, move to the next — this step-by-step approach builds a clear understanding of which setting produces which outcome. "
            "If that first trial fails, the original remains completely untouched, making it safe to try multiple approaches without pressure. "
            "For beginners especially, this habit of verifying one thing at a time turns out to be the fastest path — that is the {lens} approach to preparation."
        ),
    },
    {
        "ko": (
            "준비 단계의 핵심은 화면을 열기 전에 목적을 먼저 정의하는 것입니다. "
            "'{keyword}로 무엇을 완료 상태로 볼 것인가'를 딱 한 줄로 적어 두세요. "
            "예를 들어 '이 파일의 두 번째 섹션만 수정하고, 나머지는 건드리지 않는다'처럼 구체적으로 쓸수록 좋습니다. "
            "이렇게 목적이 명확해지면 {surfaces}를 열었을 때 어떤 옵션이 필요하고 어떤 옵션은 건드리지 말아야 하는지가 자연스럽게 보입니다. "
            "{assets}도 이 목적에 맞춰 미리 역할을 나눠 두면, 작업이 끝난 뒤 결과를 비교할 때 기준이 명확해져 검토가 훨씬 빨라집니다. "
            "목적을 적지 않고 화면부터 열면, 화면에 보이는 옵션에 이끌려 원래 필요하지 않던 것까지 손대게 되는 경우가 많습니다."
        ),
        "en": (
            "The core of the preparation stage is to define the goal before opening any screen. "
            "Write in exactly one line what counts as done for this {keyword} task. "
            "The more specific the better — for example: 'modify only the second section of this file and leave everything else untouched.' "
            "With a clear goal in place, opening {surfaces} immediately shows which options are needed and which must not be touched. "
            "Assigning roles to {assets} upfront, aligned to that goal, makes comparing outcomes after the work much faster because the baseline is unambiguous. "
            "Opening the screen before writing the goal often leads to touching settings that were not actually needed — the visible options draw attention away from the original purpose. "
            "That is why the written goal is the key setup step in a {lens}."
        ),
    },
]

STEP_LABELS = [
    ("단계별 방법", "Step-by-step approach"),
    ("적용 순서", "Application sequence"),
    ("실행 단계", "Execution steps"),
    ("진행 방식", "How to proceed"),
]

SCENARIO_LABELS = ["예제"]


def compute_text_seed(*parts):
    joined = "|".join(clean_value(part, "") for part in parts)
    return sum(ord(char) for char in joined)


def rotate_list(items, start_index):
    if not items:
        return []
    start_index %= len(items)
    return items[start_index:] + items[:start_index]


def choose_balanced_named_item(items, seed, usage_map=None, recent_items=None, attempt=0, preferred_name=None):
    if not items:
        return None

    usage_map = usage_map or {}
    recent_items = recent_items or []
    ranked = []
    total_items = len(items)

    for index, item in enumerate(items):
        name = item["name"]
        usage_penalty = usage_map.get(name, 0) * 4
        recency_penalty = 6 if recent_items[:2].count(name) else 0
        recent_penalty = 2 if name in recent_items[:4] else 0
        preferred_bonus = 8 if preferred_name and name == preferred_name else 0
        order_bias = (total_items - index) * 2
        seed_jitter = (seed + (index * 11)) % 7
        score = preferred_bonus + order_bias + seed_jitter - usage_penalty - recency_penalty - recent_penalty
        ranked.append((score, ((seed // 3) + index) % max(1, total_items), item))

    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return ranked[attempt % len(ranked)][2]


def load_qa_used(profile_name: str) -> dict[str, int]:
    """profile의 질문별 사용 횟수를 반환합니다. {question: count}"""
    if not QA_USED_PATH.exists() or QA_USED_PATH.stat().st_size == 0:
        return {}
    try:
        df = pd.read_csv(QA_USED_PATH, encoding="utf-8-sig")
    except Exception:
        return {}
    if df.empty or "profile" not in df.columns or "question" not in df.columns:
        return {}
    profile_df = df[df["profile"] == profile_name]
    return profile_df.groupby("question").size().to_dict()


def save_qa_used(profile_name: str, questions: list[str]) -> None:
    """사용된 질문 목록을 qa_used.csv에 기록합니다."""
    if not questions:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_rows = pd.DataFrame([
        {"profile": profile_name, "question": q, "used_at": now}
        for q in questions
    ])
    if QA_USED_PATH.exists() and QA_USED_PATH.stat().st_size > 0:
        try:
            existing = pd.read_csv(QA_USED_PATH, encoding="utf-8-sig")
            combined = pd.concat([existing, new_rows], ignore_index=True)
        except Exception:
            combined = new_rows
    else:
        combined = new_rows
    QA_USED_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        combined.to_csv(QA_USED_PATH, index=False, encoding="utf-8-sig")
    except PermissionError as exc:
        print(f"[warn] qa_used.csv write skipped: {exc}", flush=True)
    except Exception as exc:
        print(f"[warn] qa_used.csv update failed: {exc}", flush=True)


def create_run_state(total_count=12):
    quota = max(2, (total_count + len(STRUCTURE_VARIANTS) - 1) // len(STRUCTURE_VARIANTS))
    return {
        "structure_usage": {},
        "structure_quota": quota,
        "profile_structure_usage": {},
        "tone_usage": {},
        "narrative_usage": {},
        "pattern_usage": {},
        "block_order_usage": {},
        "recent_variants": [],
        "recent_tones": [],
        "recent_leads": [],
        "recent_endings": [],
        "recent_rhythms": [],
        "recent_transitions": [],
        "recent_profile_variants": {},
    }


def register_plan_usage(plan, run_state):
    if not run_state:
        return

    profile_name = plan["profile"]["name"]
    variant_name = plan["variant"]["name"]
    tone_name = plan["tone"]["name"]
    narrative_name = plan["narrative"]["name"]
    pattern_name = plan["scenario_pattern"]["name"]
    block_order_name = plan["scenario_block_order"]["name"]

    run_state["structure_usage"][variant_name] = run_state["structure_usage"].get(variant_name, 0) + 1
    profile_usage = run_state["profile_structure_usage"].setdefault(profile_name, {})
    profile_usage[variant_name] = profile_usage.get(variant_name, 0) + 1

    for usage_key, item_name in [
        ("tone_usage", tone_name),
        ("narrative_usage", narrative_name),
        ("pattern_usage", pattern_name),
        ("block_order_usage", block_order_name),
    ]:
        usage = run_state[usage_key]
        usage[item_name] = usage.get(item_name, 0) + 1

    run_state["recent_variants"].insert(0, variant_name)
    del run_state["recent_variants"][6:]

    run_state["recent_tones"].insert(0, tone_name)
    del run_state["recent_tones"][6:]

    run_state["recent_leads"].insert(0, plan.get("lead_slot", ""))
    del run_state["recent_leads"][6:]

    run_state["recent_endings"].insert(0, plan.get("ending_slot", ""))
    del run_state["recent_endings"][6:]

    run_state["recent_rhythms"].insert(0, plan.get("rhythm_slot", ""))
    del run_state["recent_rhythms"][6:]

    run_state["recent_transitions"].insert(0, plan.get("transition_signature", ""))
    del run_state["recent_transitions"][6:]

    profile_recent = run_state["recent_profile_variants"].setdefault(profile_name, [])
    profile_recent.insert(0, variant_name)
    del profile_recent[4:]


def make_safe_filename(text):
    text = str(text)
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = text.replace(" ", "_").strip()
    return text[:60] or "제목_없음"


def clean_value(value, fallback=""):
    if pd.isna(value):
        return fallback
    value = str(value).strip()
    return value if value else fallback


def normalize_keyword(text):
    text = str(text).lower()
    text = re.sub(r"[\s_\-]+", "", text)
    return text


_TAG_STOPWORDS = {
    "하는",
    "하기",
    "방법",
    "가이드",
    "정리",
    "실무",
    "바로",
    "쓰는",
    "사용",
    "활용",
    "처음",
    "기초",
    "완벽",
    "초보",
    "쉽게",
    "부터",
    "위한",
    "에서",
    "으로",
    "대한",
}

_PROFILE_TAG_HINTS = {
    "excel_data": ["엑셀", "업무 자동화", "데이터 정리"],
    "word_docs": ["워드", "문서 작성", "문서 정리"],
    "presentation_flow": ["파워포인트", "발표 자료", "슬라이드 구성"],
    "collaboration_system": ["협업 시스템", "업무 관리", "협업 도구"],
    "design_system": ["디자인 시스템", "컴포넌트 관리", "UI 설계"],
    "game_dev": ["게임 개발", "개발 워크플로우", "실전 세팅"],
    "ai_workflow": ["AI 활용", "업무 자동화", "프롬프트 설계"],
}


def _tokenize_tag_text(*values):
    tokens = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        parts = re.findall(r"[0-9A-Za-z가-힣]+", text)
        for part in parts:
            cleaned = part.strip()
            if len(cleaned) < 2:
                continue
            if cleaned.lower() in _TAG_STOPWORDS or cleaned in _TAG_STOPWORDS:
                continue
            tokens.append(cleaned)
    return tokens


def build_keyword_tags(plan, row, minimum=7, maximum=10):
    keyword = clean_value(plan.get("keyword", ""), "")
    title = clean_value(plan.get("title", ""), keyword)
    profile_name = clean_value(plan.get("profile", {}).get("name", ""), "")
    variant_name = clean_value(plan.get("variant", {}).get("name", ""), "")

    seen = set()
    tags = []

    def add(tag):
        tag = re.sub(r"\s+", " ", str(tag or "")).strip(" ,")
        if len(tag) < 2 or len(tag) > 40:
            return
        norm = normalize_keyword(tag)
        if not norm or norm in seen:
            return
        seen.add(norm)
        tags.append(tag)

    add(keyword)

    keyword_tokens = _tokenize_tag_text(keyword)
    title_tokens = _tokenize_tag_text(title)
    primary_tokens = keyword_tokens or title_tokens

    for token in keyword_tokens:
        add(token)

    for idx in range(len(keyword_tokens) - 1):
        add(f"{keyword_tokens[idx]} {keyword_tokens[idx + 1]}")

    if primary_tokens:
        primary = primary_tokens[0]
        add(f"{primary} 활용")
        add(f"{primary} 실무")
        add(f"{primary} 설정")

    if len(primary_tokens) >= 2:
        add(f"{primary_tokens[0]} {primary_tokens[1]}")

    for hint in _PROFILE_TAG_HINTS.get(profile_name, []):
        add(hint)

    if variant_name == "checklist_review":
        add("체크리스트")
        add("설정 점검")
        add("실수 예방")

    for token in title_tokens:
        add(token)

    fallback_tags = [
        "업무 효율화",
        "실무 가이드",
        "단계별 설정",
        "실전 활용법",
    ]
    for fallback in fallback_tags:
        add(fallback)
        if len(tags) >= minimum:
            break

    return tags[: max(minimum, maximum)]


def build_meta_description(plan):
    keyword = clean_value(plan.get("keyword", ""), "이 주제")
    variant_name = clean_value(plan.get("variant", {}).get("name", ""), "")
    if variant_name == "checklist_review":
        return (
            f"{keyword}를 실제로 적용하기 전에 꼭 확인해야 할 설정 항목, 점검 순서, "
            f"실수 예방 포인트를 실무 흐름 기준으로 정리한 메타 설명입니다."
        )
    if variant_name == "workflow_playbook":
        return (
            f"{keyword}를 업무에 바로 적용할 수 있도록 준비 단계부터 실행 순서, "
            f"검증 포인트까지 한 번에 정리한 메타 설명입니다."
        )
    if variant_name == "comparison_guide":
        return (
            f"{keyword}와 관련된 선택 기준, 차이점, 적용 상황을 빠르게 판단할 수 있도록 "
            f"핵심 기준만 정리한 메타 설명입니다."
        )
    return (
        f"{keyword}의 개념, 적용 순서, 실무 활용 포인트를 처음 보는 사람도 이해할 수 있도록 "
        f"단계별로 정리한 메타 설명입니다."
    )


def attach_article_metadata(article_text, plan, row):
    text = str(article_text or "").strip()
    if not text:
        return text, [], ""

    if re.search(r"(?mi)^태그:\s*", text) and re.search(r"(?mi)^메타 문장:\s*", text):
        tags = [part.strip() for part in re.split(r"[,\|]", re.search(r"(?mi)^태그:\s*(.+)$", text).group(1)) if part.strip()]
        meta_match = re.search(r"(?mi)^메타 문장:\s*(.+)$", text)
        return text, tags, meta_match.group(1).strip() if meta_match else ""

    tags = build_keyword_tags(plan, row)
    meta_description = build_meta_description(plan)
    metadata_block = "\n".join(
        [
            f"태그: {', '.join(tags)}",
            f"메타 문장: {meta_description}",
            "",
        ]
    )
    return f"{metadata_block}{text}".strip(), tags, meta_description


def detect_profile(row):
    keyword = normalize_keyword(row.get("keyword", ""))
    title = normalize_keyword(row.get("title", ""))
    joined = f"{keyword} {title}"

    for profile in TOOL_PROFILES:
        if any(token in joined for token in profile["tokens"]):
            return profile

    return DEFAULT_PROFILE


def choose_structure_variant(row, profile, attempt, run_state=None):
    search_intent = clean_value(row.get("search_intent", ""), "").lower()
    topic_type = clean_value(row.get("topic_type", ""), "").lower()
    keyword = normalize_keyword(row.get("keyword", ""))
    title = normalize_keyword(row.get("title", ""))
    order = PROFILE_VARIANT_ORDER.get(
        profile["name"],
        PROFILE_VARIANT_ORDER["general_practical"],
    )

    preferred_name = None
    if any(token in search_intent for token in ["자동화", "workflow", "관리", "process"]):
        preferred_name = "workflow_playbook"
    elif any(token in search_intent for token in ["오류", "해결", "problem", "issue"]):
        preferred_name = "problem_solution"
    elif "비교" in search_intent or "comparison" in search_intent:
        preferred_name = "decision_guide"
    elif any(token in keyword for token in ["설정", "옵션", "기준", "전환", "공유"]):
        preferred_name = "decision_guide"

    seed = compute_text_seed(keyword, title, search_intent, profile["name"])
    topic_preferences = TOPIC_TYPE_VARIANT_PREFERENCES.get(topic_type, [])
    if topic_preferences:
        prioritized = [name for name in topic_preferences if name in order]
        trailing = [name for name in order if name not in prioritized]
        order = prioritized + trailing
        if prioritized:
            preferred_name = prioritized[seed % len(prioritized)]
    profile_usage = {}
    recent_variants = []
    profile_recent = []
    if run_state:
        profile_usage = run_state["profile_structure_usage"].get(profile["name"], {})
        recent_variants = run_state.get("recent_variants", [])
        profile_recent = run_state["recent_profile_variants"].get(profile["name"], [])

    candidates = [STRUCTURE_BY_NAME[name] for name in order]

    if run_state:
        quota = run_state.get("structure_quota", 999)
        structure_usage = run_state.get("structure_usage", {})
        within_quota = [c for c in candidates if structure_usage.get(c["name"], 0) < quota]
        if within_quota:
            candidates = within_quota

    profile_choice = choose_balanced_named_item(
        candidates,
        seed=seed,
        usage_map=profile_usage,
        recent_items=profile_recent or recent_variants,
        attempt=attempt,
        preferred_name=preferred_name if preferred_name and any(c["name"] == preferred_name for c in candidates) else None,
    )
    if profile_choice is None:
        profile_choice = candidates[0]

    if not run_state:
        return profile_choice

    rotated_order = rotate_list(order, order.index(profile_choice["name"]))
    within_quota_names = {c["name"] for c in candidates}
    rotated_within_quota = [STRUCTURE_BY_NAME[name] for name in rotated_order if name in within_quota_names]
    if not rotated_within_quota:
        rotated_within_quota = [STRUCTURE_BY_NAME[name] for name in rotated_order]
    return choose_balanced_named_item(
        rotated_within_quota,
        seed=seed + 17,
        usage_map=run_state.get("structure_usage", {}),
        recent_items=recent_variants,
        attempt=attempt,
        preferred_name=profile_choice["name"],
    )


_GENERIC_TITLE_PATTERNS = [
    "쉽게 배우는 방법",
    "실무 활용 방법",
    "실무 활용 가이드",
    "사용 방법",
    "활용법",
]


def generate_dynamic_title(row, plan):
    keyword = clean_value(row.get("keyword", ""), "핵심 기능")
    current = clean_value(row.get("title", ""), "")
    if current and not any(p in current for p in _GENERIC_TITLE_PATTERNS):
        return current
    templates = TITLE_VARIATIONS.get(plan["variant"]["name"], ["{keyword} 사용할 때 알아야 할 것"])
    seed = plan.get("seed", compute_text_seed(keyword, plan.get("variant", {}).get("name", "")))
    return templates[seed % len(templates)].format(keyword=keyword)


def _select_qa_questions(
    qa_bank: list[str],
    qa_used_counts: dict[str, int],
    seed: int,
    attempt: int,
    count: int = 5,
) -> list[str]:
    """미사용 질문을 우선 선택합니다.

    정렬 기준:
    1. 사용 횟수 오름차순 (0회 = 미사용 최우선)
    2. 같은 사용 횟수 내에서 seed 기반 지터로 매번 다른 조합 선택
    """
    indexed = list(enumerate(qa_bank))
    jitter_seed = (seed + attempt * 13) % max(1, len(qa_bank))

    def sort_key(item):
        idx, q = item
        used = qa_used_counts.get(q, 0)
        jitter = (jitter_seed + idx * 7) % max(1, len(qa_bank))
        return (used, jitter)

    sorted_bank = sorted(indexed, key=sort_key)
    return [q for _, q in sorted_bank[:count]]


def build_article_plan(row, attempt, run_state=None, file_index=0):
    profile = detect_profile(row)
    variant = choose_structure_variant(row, profile, attempt, run_state=run_state)
    keyword = clean_value(row.get("keyword", ""), "핵심 기능")
    seed = compute_text_seed(
        row.get("keyword", ""),
        row.get("title", ""),
        row.get("search_intent", ""),
        profile["name"],
        str(file_index),
    )
    tone = choose_balanced_named_item(
        TONE_PACKS,
        seed=seed + attempt,
        usage_map=(run_state or {}).get("tone_usage", {}),
        recent_items=[],
        attempt=attempt,
    ) or TONE_PACKS[0]
    narrative = choose_balanced_named_item(
        NARRATIVE_PACKS,
        seed=(seed // 2) + attempt,
        usage_map=(run_state or {}).get("narrative_usage", {}),
        recent_items=[],
        attempt=attempt,
    ) or NARRATIVE_PACKS[0]
    scenario_pattern = choose_balanced_named_item(
        SCENARIO_PATTERNS,
        seed=(seed // 3) + attempt,
        usage_map=(run_state or {}).get("pattern_usage", {}),
        recent_items=[],
        attempt=attempt,
    ) or SCENARIO_PATTERNS[0]
    scenario_block_order = choose_balanced_named_item(
        SCENARIO_BLOCK_ORDERS,
        seed=(seed // 5) + attempt,
        usage_map=(run_state or {}).get("block_order_usage", {}),
        recent_items=[],
        attempt=attempt,
    ) or SCENARIO_BLOCK_ORDERS[0]

    scenario_bank = profile["scenario_bank"]
    scenario_count = len(scenario_bank)
    scenario_step = max(1, (seed % max(1, scenario_count - 1)) + 1)
    scenario_indices = []
    cursor = (seed + attempt) % max(1, scenario_count)
    want = min(3, scenario_count)
    for _ in range(scenario_count):
        if cursor not in scenario_indices:
            scenario_indices.append(cursor)
        if len(scenario_indices) >= want:
            break
        cursor = (cursor + scenario_step) % scenario_count
    for idx in range(scenario_count):
        if len(scenario_indices) >= want:
            break
        if idx not in scenario_indices:
            scenario_indices.append(idx)
    scenarios = [scenario_bank[index] for index in scenario_indices]

    qa_bank = profile["qa_bank"]
    qa_used_counts = load_qa_used(profile["name"])
    qa_count = REQUIRED_QA_COUNT
    questions = _select_qa_questions(qa_bank, qa_used_counts, seed=seed, attempt=attempt, count=qa_count)

    plan = {
        "keyword": keyword,
        "profile": profile,
        "variant": variant,
        "attempt": attempt + 1,
        "seed": seed,
        "tone": tone,
        "narrative": narrative,
        "scenario_pattern": scenario_pattern,
        "scenario_block_order": scenario_block_order,
        "scenarios": scenarios,
        "questions": questions,
    }
    plan["title"] = generate_dynamic_title(row, plan)
    intro_templates = INTRO_TEMPLATES.get(plan["variant"]["name"], INTRO_TEMPLATES["workflow_playbook"])
    intro_index = (plan["seed"] + plan["attempt"]) % len(intro_templates)
    conclusion_index = (plan["seed"] + plan["attempt"]) % len(CONCLUSION_TEMPLATES)
    plan["structure_slot"] = plan["variant"]["name"]
    plan["lead_slot"] = f"{plan['variant']['name']}_lead_{intro_index + 1}"
    plan["rhythm_slot"] = plan["scenario_block_order"]["name"]
    plan["style_slot"] = plan["tone"]["name"]
    plan["ending_slot"] = f"conclusion_{conclusion_index + 1}"
    plan["transition_signature"] = plan["scenario_pattern"]["name"]
    plan["qa_count"] = qa_count
    plan["scenario_count"] = REQUIRED_SCENARIO_COUNT
    return plan


def paragraph_pair(korean, english):
    return f"{korean}\n\n{english}"


def get_required_section_titles():
    return REQUIRED_SECTION_TITLES[:]


def _is_non_body_paragraph(text):
    paragraph = str(text or "").strip()
    if not paragraph:
        return True
    if re.fullmatch(r"[=\-_*~`#]{3,}", paragraph):
        return True
    first_line = paragraph.splitlines()[0].strip()
    if first_line.startswith(("제목:", "플랫폼:", "핵심 키워드:", "구조 타입:", "주제 프로필:", "태그:", "메타 문장:")):
        return True
    if re.match(r"^Q\d+\.\s+", first_line):
        return True
    if re.match(rf"^({'|'.join(map(re.escape, SCENARIO_LABELS + ['체크 항목', '비교 장면', '처음 효과 장면', 'Check item', 'Comparison scene', 'First-try scene']))})\s+\d+\.", first_line):
        return True
    if re.match(r"^\d+\.\s+\S+", first_line):
        return True
    if re.match(r"^[-*+]\s+", first_line):
        return True
    return False


def _classify_bilingual_paragraph(text):
    paragraph = str(text or "").strip()
    if _is_non_body_paragraph(paragraph):
        return "skip"
    korean_count = len(re.findall(r"[가-힣]", paragraph))
    english_count = len(re.findall(r"[A-Za-z]", paragraph))
    if korean_count >= 20 and korean_count >= english_count:
        return "ko"
    if english_count >= 20 and english_count > korean_count:
        return "en"
    return "other"


def analyze_bilingual_structure(text):
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", str(text or "")) if part.strip()]
    body_types = []
    for paragraph in paragraphs:
        paragraph_type = _classify_bilingual_paragraph(paragraph)
        if paragraph_type == "skip":
            continue
        body_types.append(paragraph_type)

    runs = []
    for paragraph_type in body_types:
        if runs and runs[-1][0] == paragraph_type:
            runs[-1][1] += 1
        else:
            runs.append([paragraph_type, 1])

    korean_blocks = sum(1 for p in body_types if p == "ko")
    english_blocks = sum(1 for p in body_types if p == "en")
    paired_blocks = 0
    missing_english_after_korean = 0

    idx = 0
    while idx < len(runs):
        run_type, run_count = runs[idx]
        if run_type == "ko":
            next_type = runs[idx + 1][0] if idx + 1 < len(runs) else ""
            if next_type == "en":
                paired_blocks += run_count
                idx += 2
                continue
            missing_english_after_korean += run_count
        idx += 1

    return {
        "korean_blocks": korean_blocks,
        "english_blocks": english_blocks,
        "paired_blocks": paired_blocks,
        "missing_english_after_korean": missing_english_after_korean,
        "is_bilingual": korean_blocks > 0 and missing_english_after_korean == 0 and english_blocks >= korean_blocks,
    }


def has_required_bilingual_structure(text):
    return analyze_bilingual_structure(text)["is_bilingual"]


def analyze_required_article_structure(text):
    scenario_numbers = []
    qa_numbers = []
    found_section_titles = []
    scenario_prefixes = SCENARIO_LABELS + ["체크 항목", "비교 장면", "처음 효과 장면", "Check item", "Comparison scene", "First-try scene"]

    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        section_match = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if section_match:
            found_section_titles.append(f"{section_match.group(1)}. {section_match.group(2).strip()}")

        scenario_match = re.match(rf"^({'|'.join(map(re.escape, scenario_prefixes))})\s+(\d+)\.", stripped)
        if scenario_match:
            scenario_numbers.append(int(scenario_match.group(2)))

        qa_match = re.match(r"^Q(\d+)\.\s+", stripped)
        if qa_match:
            qa_numbers.append(int(qa_match.group(1)))

    unique_scenarios = sorted(set(scenario_numbers))
    unique_qas = sorted(set(qa_numbers))
    expected_scenarios = list(range(1, REQUIRED_SCENARIO_COUNT + 1))
    expected_qas = list(range(1, REQUIRED_QA_COUNT + 1))
    expected_section_titles = [f"{i + 1}. {title}" for i, title in enumerate(REQUIRED_SECTION_TITLES)]

    return {
        "scenario_numbers": scenario_numbers,
        "qa_numbers": qa_numbers,
        "unique_scenarios": unique_scenarios,
        "unique_qas": unique_qas,
        "found_section_titles": found_section_titles,
        "expected_section_titles": expected_section_titles,
        "has_required_sections": found_section_titles[: len(expected_section_titles)] == expected_section_titles,
        "has_required_scenarios": unique_scenarios == expected_scenarios,
        "has_required_qas": unique_qas == expected_qas,
    }


def has_required_article_structure(text):
    analysis = analyze_required_article_structure(text)
    return (
        analysis["has_required_sections"]
        and analysis["has_required_scenarios"]
        and analysis["has_required_qas"]
    )


def count_korean_content_chars(text):
    """Count only Korean body characters.

    Excludes English, digits, symbols, and common non-body lines such as
    lists, tables, code blocks, images, and section headings.
    """
    if not text:
        return 0

    korean_count = 0
    in_code_block = False

    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if re.fullmatch(r"[=\-_*~`#]{3,}", line):
            continue
        if line.startswith("![") or "<img" in line.lower():
            continue
        if "|" in line:
            continue
        if re.match(r"^\d+\.\s*$", line):
            continue
        if re.match(r"^\d+\.\s+\S+", line):
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        if re.match(r"^[-*+•]\s+", line):
            continue

        korean_count += len(re.findall(r"[가-힣]", line))

    return korean_count


def _count_hangul_chars(text):
    return len(re.findall(r"[\uAC00-\uD7A3]", str(text or "")))


def _classify_bilingual_paragraph(text):
    paragraph = str(text or "").strip()
    if _is_non_body_paragraph(paragraph):
        return "skip"
    first_line = paragraph.splitlines()[0].strip()
    korean_count = _count_hangul_chars(paragraph)
    english_count = len(re.findall(r"[A-Za-z]", paragraph))
    if english_count >= 15 and re.match(r"^(Q\d+\.|[A-Za-z])", first_line):
        return "en"
    if korean_count >= 20 and korean_count >= english_count:
        return "ko"
    if english_count >= 20 and english_count > korean_count:
        return "en"
    return "other"


def count_korean_content_chars(text):
    """Count only Korean body characters.

    Excludes English, digits, symbols, and common non-body lines such as
    lists, tables, code blocks, images, and section headings.
    """
    if not text:
        return 0

    korean_count = 0
    in_code_block = False

    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if re.fullmatch(r"[=\-_*~`#]{3,}", line):
            continue
        if line.startswith("![") or "<img" in line.lower():
            continue
        if "|" in line:
            continue
        if re.match(r"^\d+\.\s*$", line):
            continue
        if re.match(r"^\d+\.\s+\S+", line):
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        if re.match(r"^[-*+]\s+", line):
            continue

        korean_count += _count_hangul_chars(line)

    return korean_count


def plan_tone(plan):
    return plan.get("tone", TONE_PACKS[0])


def plan_pattern(plan):
    return plan.get("scenario_pattern", SCENARIO_PATTERNS[0])


def plan_narrative(plan):
    return plan.get("narrative", NARRATIVE_PACKS[0])


def plan_block_order(plan):
    return plan.get("scenario_block_order", SCENARIO_BLOCK_ORDERS[0])


def choose_from_seed(options, seed):
    if not options:
        return ""
    return options[seed % len(options)]


def _sentence_lengths(text):
    sentences = [part.strip() for part in re.split(r"[.!?\n]+", str(text)) if part.strip()]
    return [len(sentence) for sentence in sentences]


def _average_sentence_length(text):
    lengths = _sentence_lengths(text)
    if not lengths:
        return 0
    return round(sum(lengths) / len(lengths), 2)


def _paragraph_count(text):
    return len([part for part in re.split(r"\n\s*\n", str(text)) if part.strip()])


def _soft_duplication_penalty(score, structural_score):
    penalty = 0
    if 0.62 <= score <= 0.81:
        penalty += 30
    elif 0.52 <= score <= 0.61:
        penalty += 15

    if 0.60 <= structural_score <= 0.71:
        penalty += 20
    elif 0.52 <= structural_score <= 0.59:
        penalty += 10
    return penalty


def evaluate_quality(plan, article_text, match, structural_match, run_state=None):
    run_state = run_state or {}
    penalties = {
        "structure": 0,
        "rhythm": 0,
        "style": 0,
        "transition": 0,
        "ending": 0,
        "duplication_soft": _soft_duplication_penalty(match.score, structural_match.score),
    }
    reasons = []

    recent_variants = run_state.get("recent_variants", [])
    if recent_variants[:1].count(plan["structure_slot"]):
        penalties["structure"] += 15
        reasons.append("same structure slot as previous output")
    if recent_variants[:5].count(plan["structure_slot"]) >= 2:
        penalties["structure"] += 10
        reasons.append("structure slot concentrated in recent outputs")

    recent_rhythms = run_state.get("recent_rhythms", [])
    if recent_rhythms[:1].count(plan["rhythm_slot"]):
        penalties["rhythm"] += 10
        reasons.append("same rhythm slot as previous output")

    recent_tones = run_state.get("recent_tones", [])
    if recent_tones[:2].count(plan["style_slot"]) >= 1:
        penalties["style"] += 12
        reasons.append("style slot repeated in recent outputs")

    recent_transitions = run_state.get("recent_transitions", [])
    if recent_transitions[:2].count(plan["transition_signature"]) >= 1:
        penalties["transition"] += 8
        reasons.append("transition signature repeated")

    recent_endings = run_state.get("recent_endings", [])
    if recent_endings[:1].count(plan["ending_slot"]):
        penalties["ending"] += 8
        reasons.append("ending slot repeated")
    if recent_variants[:1].count(plan["structure_slot"]) and recent_endings[:1].count(plan["ending_slot"]):
        penalties["ending"] += 10
        reasons.append("same structure and ending pairing repeated")

    total_penalty = sum(penalties.values())
    if not reasons:
        reasons.append("no major diversity concentration detected")

    return {
        "structure_slot": plan["structure_slot"],
        "lead_slot": plan["lead_slot"],
        "rhythm_slot": plan["rhythm_slot"],
        "style_slot": plan["style_slot"],
        "ending_slot": plan["ending_slot"],
        "transition_signature": plan["transition_signature"],
        "avg_sentence_length": _average_sentence_length(article_text),
        "paragraph_count": _paragraph_count(article_text),
        "penalty_structure": penalties["structure"],
        "penalty_rhythm": penalties["rhythm"],
        "penalty_style": penalties["style"],
        "penalty_transition": penalties["transition"],
        "penalty_ending": penalties["ending"],
        "penalty_duplication_soft": penalties["duplication_soft"],
        "total_penalty": total_penalty,
        "decision_reason": "; ".join(reasons),
    }


def append_quality_log(rows):
    if not rows:
        return CONTENT_QUALITY_LOG_PATH

    CONTENT_QUALITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(rows)
    if CONTENT_QUALITY_LOG_PATH.exists() and CONTENT_QUALITY_LOG_PATH.stat().st_size > 0:
        try:
            existing = pd.read_csv(CONTENT_QUALITY_LOG_PATH, encoding="utf-8-sig")
            combined = pd.concat([existing, new_df], ignore_index=True)
        except Exception:
            combined = new_df
    else:
        combined = new_df

    combined.to_csv(CONTENT_QUALITY_LOG_PATH, index=False, encoding="utf-8-sig")
    return CONTENT_QUALITY_LOG_PATH


def render_intro(keyword, profile, plan):
    surfaces = ", ".join(profile["surfaces"][:3])
    assets = ", ".join(profile["assets"][:3])
    variant = plan["variant"]["name"]
    tone = plan_tone(plan)
    narrative = plan_narrative(plan)

    templates = INTRO_TEMPLATES.get(variant, INTRO_TEMPLATES["workflow_playbook"])
    tmpl_index = (plan["seed"] + plan["attempt"]) % len(templates)
    ko_tmpl, en_tmpl = templates[tmpl_index]

    ko = ko_tmpl.format(
        keyword=keyword,
        surfaces=surfaces,
        assets=assets,
        workflow=profile["workflow"],
    )
    en = en_tmpl.format(
        keyword=keyword,
        surfaces=surfaces,
        assets=assets,
        workflow=profile["workflow"],
        hook=tone["hook"],
        lens=tone["lens"],
    )

    return paragraph_pair(ko, en + " " + narrative["intro_close"])


def render_principles(keyword, profile, plan):
    variant = plan["variant"]
    focus_text = " / ".join(variant["section_focus"])
    pitfalls = ", ".join(profile["pitfalls"][:3])
    surfaces = ", ".join(profile["surfaces"][:4])
    assets = ", ".join(profile["assets"])
    tone = plan_tone(plan)
    narrative = plan_narrative(plan)

    base_angle = PROFILE_PRINCIPLES_ANGLE.get(profile["name"], 0)
    body_index = (base_angle + plan["attempt"]) % len(PRINCIPLES_BODIES)
    note_index = (plan["seed"] + plan["attempt"]) % len(PRINCIPLES_ASSET_NOTES)

    body = PRINCIPLES_BODIES[body_index]
    note = PRINCIPLES_ASSET_NOTES[note_index]

    ko = body["ko"].format(keyword=keyword, focus_text=focus_text, surfaces=surfaces, pitfalls=pitfalls)
    en = body["en"].format(keyword=keyword, focus_text=focus_text, surfaces=surfaces, pitfalls=pitfalls, risk_label=tone["risk_label"])

    ko2 = note["ko"].format(keyword=keyword, assets=assets)
    en2 = note["en"].format(keyword=keyword, assets=assets)

    principle_blocks = [
        paragraph_pair(ko, en + " " + narrative["principle_close"]),
        paragraph_pair(ko2, en2),
    ]
    if (plan["seed"] + plan["attempt"]) % 2:
        principle_blocks.reverse()
    return "\n\n".join(principle_blocks)


def render_preparation(keyword, profile, plan):
    surfaces = ", ".join(profile["surfaces"][:3])
    assets = ", ".join(profile["assets"][:3])
    tone = plan_tone(plan)
    narrative = plan_narrative(plan)

    prep_index = (plan["seed"] + plan["attempt"] * 3) % len(PREPARATION_BODIES)
    body = PREPARATION_BODIES[prep_index]

    ko = body["ko"].format(keyword=keyword, assets=assets, surfaces=surfaces)
    en = body["en"].format(keyword=keyword, assets=assets, surfaces=surfaces, lens=tone["lens"])
    return paragraph_pair(ko, en + " " + narrative["prep_close"])


def build_example_steps(profile, scenario, index, plan):
    surfaces = profile["surfaces"]
    assets = profile["assets"]
    ko_patterns = [
        [
            f"{surfaces[0]}에서 작업 대상 화면을 열고 {assets[0]}을 기준본으로 고정합니다.",
            f"{surfaces[1]} 또는 {surfaces[2]}에서 {scenario.split()[0]}와 직접 연결되는 옵션만 먼저 활성화합니다.",
            f"{assets[min(1, len(assets) - 1)]}에 샘플 데이터를 넣거나 테스트 장면을 만들어 결과 변화를 확인합니다.",
            f"{surfaces[min(3, len(surfaces) - 1)]}에서 변경 범위와 저장 대상을 다시 점검한 뒤 확정합니다.",
        ],
        [
            f"{assets[0]}과 {assets[min(1, len(assets) - 1)]}를 분리해서 원본과 검토본의 역할을 먼저 나눕니다.",
            f"{surfaces[0]}에서 현재 상태를 기록한 뒤 {surfaces[1]}에서 핵심 옵션 하나만 바꿉니다.",
            f"{surfaces[min(2, len(surfaces) - 1)]}에서 바뀐 결과를 캡처하거나 메모해 이전 상태와 비교합니다.",
            f"{surfaces[min(3, len(surfaces) - 1)]}에서 저장 기준과 공유 범위를 확인한 후 반영합니다.",
        ],
        [
            f"{surfaces[0]}에서 관련 항목을 모두 열어 두고 {scenario.split()[0]}와 무관한 선택지를 먼저 제외합니다.",
            f"{assets[min(1, len(assets) - 1)]}에 작은 샘플을 준비해 가장 위험한 변경부터 시험합니다.",
            f"{surfaces[min(2, len(surfaces) - 1)]} 또는 {surfaces[min(3, len(surfaces) - 1)]}에서 결과를 검토하며 기준값을 미세 조정합니다.",
            f"마지막에 {assets[-1]} 또는 공유본에서 같은 결과가 재현되는지 확인합니다.",
        ],
        [
            f"먼저 {assets[0]}을 복제하고 {surfaces[0]}에서 되돌릴 수 있는 상태를 만들어 둡니다.",
            f"{surfaces[1]}에서 핵심 옵션을 선택한 뒤 {surfaces[min(2, len(surfaces) - 1)]}에서 적용 범위를 좁혀 시험합니다.",
            f"{assets[min(1, len(assets) - 1)]}과 실제 대상 사이의 차이를 체크하며 부작용이 없는지 봅니다.",
            f"이상이 없으면 {surfaces[min(3, len(surfaces) - 1)]}에서 최종 반영하고 기록을 남깁니다.",
        ],
    ]
    en_patterns = [
        [
            f"Open the target screen on {surfaces[0]} and fix {assets[0]} as the reference copy.",
            f"Activate only the options directly tied to the task on {surfaces[1]} or {surfaces[2]}.",
            f"Insert sample data into {assets[min(1, len(assets) - 1)]} and verify how the result changes.",
            f"Review the change scope and save target on {surfaces[min(3, len(surfaces) - 1)]}, then confirm.",
        ],
        [
            f"Separate {assets[0]} and {assets[min(1, len(assets) - 1)]} to assign source and review roles first.",
            f"Record the current state on {surfaces[0]}, then change only one key option on {surfaces[1]}.",
            f"Capture or note the changed result on {surfaces[min(2, len(surfaces) - 1)]} and compare with the previous state.",
            f"Confirm the save criteria and sharing scope on {surfaces[min(3, len(surfaces) - 1)]}, then apply.",
        ],
        [
            f"Open all related items on {surfaces[0]} and exclude unrelated options first.",
            f"Prepare a small sample in {assets[min(1, len(assets) - 1)]} and test the riskiest change first.",
            f"Review results on {surfaces[min(2, len(surfaces) - 1)]} or {surfaces[min(3, len(surfaces) - 1)]} and fine-tune the baseline.",
            f"Finally confirm that the same result is reproduced in {assets[-1]} or a shared copy.",
        ],
        [
            f"Duplicate {assets[0]} first and create a recoverable state on {surfaces[0]}.",
            f"Select the key option on {surfaces[1]}, then narrow the scope on {surfaces[min(2, len(surfaces) - 1)]} before testing.",
            f"Check the difference between {assets[min(1, len(assets) - 1)]} and the actual target and confirm there are no side effects.",
            f"If all is clear, apply the final change on {surfaces[min(3, len(surfaces) - 1)]} and leave a record.",
        ],
    ]
    step_seed = plan["seed"] + (plan["attempt"] * 5) + index
    pattern_index = step_seed % len(ko_patterns)
    return ko_patterns[pattern_index], en_patterns[pattern_index]


def render_scenario(keyword, profile, plan, scenario, index):
    ko_steps_list, en_steps_list = build_example_steps(profile, scenario, index, plan)
    pitfall = profile["pitfalls"][index % len(profile["pitfalls"])]
    asset = profile["assets"][index % len(profile["assets"])]
    tone = plan_tone(plan)
    pattern = plan_pattern(plan)
    narrative = plan_narrative(plan)
    block_order = plan_block_order(plan)

    scenario_label = SCENARIO_LABELS[(plan["seed"] + index) % len(SCENARIO_LABELS)]
    step_ko_label, step_en_label = STEP_LABELS[(plan["seed"] + plan["attempt"] + index) % len(STEP_LABELS)]

    shared_title = f"{scenario_label} {index + 1}. {scenario} [{pattern['intro_label']}]"

    ko_intro = (
        f"상황 설명: {keyword}를 사용할 때 가장 흔하게 발생하는 실수는, 작업 목적을 먼저 확인하지 않고 화면 조작부터 따라가는 것입니다. "
        f"화면에서 눈에 띄는 버튼이나 메뉴를 먼저 클릭하면 자연스럽게 느껴지지만, "
        f"어디까지 바꿀 것인지 범위를 정하지 않으면 나중에 예상치 못한 부분까지 바뀌어 있는 경우가 생깁니다. "
        f"이 장면에서는 {asset}을 기준으로 '어디까지가 이번 작업의 범위인지'를 먼저 정하고 시작하는 것이 핵심입니다. "
        f"범위를 정할 때는 '이번에 바꿔야 하는 것'과 '바꾸면 안 되는 것'을 한 줄씩 적어 두면 판단이 훨씬 쉬워집니다. "
        f"이 과정이 번거롭게 느껴질 수 있지만, 이 한 단계가 나중에 잘못된 결과를 되돌리는 데 드는 시간을 크게 줄여 줍니다."
    )
    en_intro = (
        f"Situation: The most common mistake with {keyword} is clicking through screen menus before clarifying the work goal. "
        f"Starting with what is visually obvious on screen feels natural, but without defining the change scope first, "
        f"unexpected areas often end up modified. "
        f"In this scene, the key is to define the boundary of 'how far this task goes' using {asset} as the reference point before touching anything. "
        f"When setting the boundary, writing one line for 'what must change' and one line for 'what must not change' makes the judgment much easier. "
        f"This step may feel like extra work, but it significantly reduces the time spent undoing incorrect results later. "
        f"{narrative['reason_frame']}"
    )

    ko_reason = (
        f"왜 이 순서가 중요한가: {profile['workflow']} 과정에서 가장 판단이 어려운 순간은 '지금 이 옵션을 바꿔도 되는가'를 결정해야 할 때입니다. "
        f"이 시나리오는 그 판단 기준을 미리 세우는 단계를 가장 선명하게 보여 주는 예제입니다. "
        f"작업 전에 변경 범위와 기준을 정해 두면, 작업 중에 선택의 기로에 섰을 때 기준에 맞는지 비교해보면 되기 때문에 판단 속도가 빨라집니다. "
        f"반대로 기준 없이 진행하면 {pitfall} 같은 문제가 작업 후반이나 공유 직전에 나타나고, "
        f"그 시점에서 되돌리려면 이전 단계까지 전부 재작업해야 하는 상황이 생길 수 있습니다. "
        f"이 예제를 통해 '언제 멈추고 확인해야 하는지'의 판단 기준을 익혀 두면, 비슷한 상황에서 같은 실수를 반복하지 않게 됩니다."
    )
    en_reason = (
        f"{pattern['reason_label']}: The hardest moment in {profile['workflow']} is deciding whether a given option can be changed right now. "
        f"This scenario shows most clearly the step of establishing that decision baseline before the work starts. "
        f"When the change scope and criteria are set in advance, mid-task decisions become faster because you simply compare against the baseline. "
        f"Without a baseline, issues such as {pitfall} tend to surface late in the process or just before sharing, "
        f"and reverting at that point may require redoing every step that came after. "
        f"Internalizing 'when to stop and verify' from this example prevents repeating the same mistake in similar situations — that is the practical value of a {tone['lens']}."
    )

    ko_steps = f"{step_ko_label}:\n" + "\n".join(f"- {step}" for step in ko_steps_list)
    en_steps = f"{step_en_label}:\n" + "\n".join(f"- {step}" for step in en_steps_list)

    ko_caution = (
        f"주의사항: {pitfall}는 대부분 두 가지 상황에서 발생합니다. "
        f"첫 번째는 한 번에 여러 옵션을 동시에 바꾸는 경우이고, 두 번째는 원본과 테스트본을 같은 폴더에 두고 섞어서 쓰는 경우입니다. "
        f"어느 쪽이든 나중에 문제가 생겼을 때 '어떤 변경이 문제를 일으켰는지'를 찾기가 매우 어려워집니다. "
        f"적용 직후에는 바로 저장하지 말고, 화면 위아래를 천천히 훑으면서 예상하지 못한 변경이 없는지 먼저 확인하세요. "
        f"특히 처음 사용하는 기능이라면, 확인 전에 저장하는 습관을 만들지 않는 것이 중요합니다. "
        f"저장 전 30초 확인이 나중에 몇 시간의 복구 작업을 막아 줄 수 있습니다."
    )
    en_caution = (
        f"{pattern['caution_label']}: {pitfall} typically arises in two situations. "
        f"First, when multiple options are changed at the same time. "
        f"Second, when the original and test copies sit in the same folder and get used interchangeably. "
        f"In either case, tracing which change caused a problem later becomes very difficult. "
        f"Do not save immediately after applying the change; scroll through the screen slowly and confirm nothing unexpected shifted. "
        f"This is especially important with a feature you are using for the first time — do not build the habit of saving before verifying. "
        f"A thirty-second check before saving can prevent several hours of recovery work. {narrative['caution_frame']}"
    )

    blocks = {
        "intro": shared_title + "\n\n" + paragraph_pair(ko_intro, en_intro),
        "reason": paragraph_pair(ko_reason, en_reason),
        "steps": paragraph_pair(ko_steps, en_steps),
        "caution": paragraph_pair(ko_caution, en_caution),
    }
    return "\n\n".join(blocks[name] for name in block_order["order"])


def render_checklist_item(keyword, profile, plan, scenario, index):
    surfaces = profile["surfaces"]
    assets = profile["assets"]
    pitfall = profile["pitfalls"][index % len(profile["pitfalls"])]
    asset = assets[index % len(assets)]
    surface = surfaces[index % len(surfaces)]
    tone = plan_tone(plan)
    item_num = index + 1

    ko = (
        f"체크 항목 {item_num}. {scenario}\n\n"
        f"왜 필요한가: 이 항목을 빠뜨리면 {pitfall} 같은 문제가 뒤늦게 발생합니다. "
        f"{surface}에서 직접 확인하지 않으면 놓치기 쉬운 부분입니다.\n\n"
        f"확인 방법:\n"
        f"1) {asset}에서 현재 값이 의도한 상태인지 먼저 확인합니다.\n"
        f"2) {surfaces[min(1, len(surfaces)-1)]}에서 해당 항목이 올바르게 설정되어 있는지 점검합니다.\n"
        f"3) 조정이 필요하면 {surfaces[min(2, len(surfaces)-1)]}에서 수정 후 저장합니다.\n\n"
        f"주의사항: 이 항목은 {pitfall}과 직접 연결되어 있어 건너뛰면 이후 확인이 무의미해질 수 있습니다."
    )
    en = (
        f"Check item {item_num}. {scenario}\n\n"
        f"Why it matters: Skipping this item often causes {pitfall} to appear later when it is harder to fix. "
        f"It is easy to miss without directly checking {surface}.\n\n"
        f"How to verify:\n"
        f"1) Confirm the current value in {asset} matches the intended state.\n"
        f"2) Check the setting is correctly configured on {surfaces[min(1, len(surfaces)-1)]}.\n"
        f"3) If adjustment is needed, apply changes on {surfaces[min(2, len(surfaces)-1)]} and save.\n\n"
        f"Caution: This item is directly tied to {pitfall}. Skipping it can make later checks meaningless. [{tone['risk_label']}]"
    )
    return paragraph_pair(ko, en)


def render_comparison_item(keyword, profile, plan, scenario, index):
    surfaces = profile["surfaces"]
    assets = profile["assets"]
    pitfall = profile["pitfalls"][index % len(profile["pitfalls"])]
    asset = assets[index % len(assets)]
    surface = surfaces[index % len(surfaces)]
    tone = plan_tone(plan)
    item_num = index + 1

    ko = (
        f"비교 장면 {item_num}. {scenario}\n\n"
        f"방식 A — {assets[0]} 기준 접근:\n"
        f"{surface}에서 {assets[0]}을 먼저 고정하고 범위를 좁혀서 진행합니다. "
        f"변경 후 영향 범위가 예측 가능해 {pitfall} 위험이 낮습니다.\n\n"
        f"방식 B — {surfaces[min(1, len(surfaces)-1)]} 기준 접근:\n"
        f"{surfaces[min(1, len(surfaces)-1)]}에서 직접 옵션을 선택해 빠르게 적용합니다. "
        f"속도는 빠르지만 {pitfall} 쪽으로 번질 가능성을 미리 확인해야 합니다.\n\n"
        f"이 상황에서의 선택 기준: {scenario}가 반복 작업이라면 방식 A, 일회성이라면 방식 B가 유리합니다."
    )
    en = (
        f"Comparison scene {item_num}. {scenario}\n\n"
        f"Approach A — anchored to {assets[0]}:\n"
        f"Fix {assets[0]} first on {surface} and narrow the scope. "
        f"The impact range after changes stays predictable, reducing {pitfall} risk.\n\n"
        f"Approach B — anchored to {surfaces[min(1, len(surfaces)-1)]}:\n"
        f"Select options directly on {surfaces[min(1, len(surfaces)-1)]} for faster application. "
        f"Speed is higher but potential drift toward {pitfall} must be confirmed first.\n\n"
        f"Decision rule: For a repeating task, Approach A fits better. For a one-time case, Approach B is usually faster. [{tone['lens']}]"
    )
    return paragraph_pair(ko, en)


def render_quickstart_item(keyword, profile, plan, scenario, index):
    surfaces = profile["surfaces"]
    assets = profile["assets"]
    pitfall = profile["pitfalls"][index % len(profile["pitfalls"])]
    asset = assets[index % len(assets)]
    surface = surfaces[index % len(surfaces)]
    tone = plan_tone(plan)
    ko_steps_list, en_steps_list = build_example_steps(profile, scenario, index, plan)
    item_num = index + 1

    step_lines_ko = "\n".join(f"{i+1}) {step}" for i, step in enumerate(ko_steps_list))
    step_lines_en = "\n".join(f"{i+1}) {step}" for i, step in enumerate(en_steps_list))

    ko = (
        f"처음 써볼 장면 {item_num}. {scenario}\n\n"
        f"어렵지 않습니다. {surface}에서 시작하면 됩니다.\n\n"
        f"따라하는 방법:\n{step_lines_ko}\n\n"
        f"처음 하다 보면 {pitfall} 때문에 막힐 수 있습니다. "
        f"그럴 때는 {asset}을 한 번 더 확인하고 다시 시도해 보세요."
    )
    en = (
        f"First-try scene {item_num}. {scenario}\n\n"
        f"It is straightforward. Start on {surface}.\n\n"
        f"Steps to follow:\n{step_lines_en}\n\n"
        f"First-timers often hit {pitfall} here. "
        f"When that happens, double-check {asset} and try again. [{tone['lens']}]"
    )
    return paragraph_pair(ko, en)


def render_review_or_exception(keyword, profile, plan):
    variant_name = plan["variant"]["name"]
    pitfalls = ", ".join(profile["pitfalls"][:2])
    surfaces = ", ".join(profile["surfaces"][:3])
    tone = plan_tone(plan)
    narrative = plan_narrative(plan)

    if variant_name == "standardization_blueprint":
        ko = (
            f"{keyword}를 표준 절차로 굳힐 때는 개인 기억에 남기는 대신, {surfaces}에서 어떤 값을 고정했는지 문서로 남겨야 합니다. "
            f"특히 예외 처리 기준을 따로 써 두지 않으면 담당자가 바뀌는 순간 {pitfalls} 같은 문제가 반복됩니다. "
            f"템플릿, 권한, 검토 순서를 한 문서에 묶어 두면 재사용성과 설명 가능성이 함께 올라갑니다."
        )
        en = (
            f"When turning {keyword} into a standard routine, document which values were fixed on screens such as {surfaces} instead of relying on memory. "
            f"If exception rules are not written separately, issues such as {pitfalls} repeat as soon as the owner changes. "
            f"Keeping the template, permissions, and review order in one document improves both reuse and explainability during {tone['review_label']}."
        )
    elif variant_name == "decision_guide":
        ko = (
            f"검증 단계에서는 결과가 나왔다는 사실보다 결과가 기대한 목적과 맞는지를 보는 편이 중요합니다. "
            f"{keyword}로 시간이 줄어든 것처럼 보여도 실제로는 적용 범위가 넓어져 후속 수정이 늘 수 있습니다. "
            f"그래서 최종 확인에서는 성공 사례뿐 아니라 멈춰야 하는 기준도 함께 적어 두는 것이 좋습니다."
        )
        en = (
            f"In the verification stage, it is more important to check whether the result matches the goal than to celebrate the fact that a result exists. "
            f"Even when {keyword} appears to save time, the target scope may have expanded and created more follow-up edits. "
            f"For that reason, the final checklist should include not only success criteria but also stop conditions under {tone['review_label']}."
        )
    elif variant_name == "checklist_review":
        ko = (
            f"{keyword}를 점검할 때 모든 항목을 다 확인했다고 해서 끝이 아닙니다. "
            f"빠뜨린 항목 하나가 나중에 {pitfalls} 같은 문제로 이어지는 경우가 있습니다. "
            f"마지막 단계에서는 확인한 항목을 목록으로 남겨 두면, 다음번에 같은 점검을 반복할 때 훨씬 빠릅니다."
        )
        en = (
            f"Finishing all checklist items for {keyword} is not the end. "
            f"A single skipped item can lead to problems such as {pitfalls} later on. "
            f"At the final stage, recording the verified items as a list makes the next review significantly faster under {tone['review_label']}."
        )
    elif variant_name == "comparison_guide":
        ko = (
            f"두 방식 중 어느 쪽을 선택했더라도, 선택한 이유를 한 줄이라도 기록해 두는 것이 중요합니다. "
            f"다음에 같은 상황이 왔을 때 처음부터 다시 비교하지 않아도 되기 때문입니다. "
            f"기록이 없으면 {pitfalls} 같은 문제가 반복될 때 어느 방식에서 생긴 건지 파악하기 어렵습니다."
        )
        en = (
            f"Whichever approach you chose for {keyword}, note the reason in one line. "
            f"When the same situation comes back, that record removes the need to compare from scratch. "
            f"Without it, repeat issues such as {pitfalls} become harder to trace back to a specific approach under {tone['review_label']}."
        )
    elif variant_name == "quickstart_entry":
        ko = (
            f"{keyword}를 처음 써봤을 때의 경험을 빠르게 기록해 두는 것이 좋습니다. "
            f"어디서 막혔는지, 어떻게 해결했는지를 메모해 두면 다음번에 같은 지점에서 시간을 낭비하지 않습니다. "
            f"초보 단계에서 {pitfalls} 같은 문제를 먼저 한 번 겪어 두는 것이 오히려 빠른 성장으로 이어집니다."
        )
        en = (
            f"After your first session with {keyword}, quickly record what you tried and where you got stuck. "
            f"That note saves time when the same friction appears again. "
            f"Running into {pitfalls} early on actually accelerates learning faster than avoiding it under {tone['review_label']}."
        )
    else:
        ko = (
            f"작업이 끝난 뒤에는 결과만 저장하지 말고 검토 기준도 함께 남겨 두는 편이 좋습니다. "
            f"{keyword}는 화면 조작보다 해석 기준이 더 중요한 기능이기 때문에, 어떤 값이 바뀌면 성공으로 볼지 정해 두어야 합니다. "
            f"이 기록이 있어야 다음 작업에서 같은 시행착오를 반복하지 않습니다."
        )
        en = (
            f"After finishing the work, keep the review criteria together with the result instead of saving the result alone. "
            f"Because {keyword} depends more on interpretation than on raw clicking, define which changed values count as success. "
            f"That record prevents the same trial and error from repeating in the next run and improves {tone['review_label']}."
        )

    return paragraph_pair(ko, en + " " + narrative["review_close"])


def render_qna(keyword, profile, plan):
    qna_blocks = []
    tone = plan_tone(plan)
    narrative = plan_narrative(plan)
    for index, question in enumerate(plan["questions"], start=1):
        pitfall = profile["pitfalls"][(index - 1) % len(profile["pitfalls"])]
        surface = profile["surfaces"][(index - 1) % len(profile["surfaces"])]
        asset = profile["assets"][(index - 1) % len(profile["assets"])]

        tmpl_index = (plan["seed"] + index + plan["attempt"]) % len(QA_ANSWER_TEMPLATES)
        tmpl = QA_ANSWER_TEMPLATES[tmpl_index]

        shared_q = f"Q{index}. {question}"
        ko_a = tmpl["ko"].format(surface=surface, asset=asset, pitfall=pitfall)
        en_a = tmpl["en"].format(
            surface=surface,
            asset=asset,
            pitfall=pitfall,
            tip_label=tone["tip_label"],
            qa_close=narrative["qa_close"],
        )
        qna_blocks.append(shared_q + "\n\n" + paragraph_pair(ko_a, en_a))

    return "\n\n".join(qna_blocks)


def render_conclusion(keyword, profile, plan):
    tone = plan_tone(plan)
    narrative = plan_narrative(plan)

    tmpl_index = (plan["seed"] + plan["attempt"]) % len(CONCLUSION_TEMPLATES)
    tmpl = CONCLUSION_TEMPLATES[tmpl_index]

    ko = tmpl["ko"].format(keyword=keyword)
    en = tmpl["en"].format(
        keyword=keyword,
        lens=tone["lens"],
        conclusion_close=narrative["conclusion_close"],
    )
    return paragraph_pair(ko, en)


def render_article_locally(row, plan):
    title = plan["title"]
    keyword = plan["keyword"]
    profile = plan["profile"]
    section_titles = get_required_section_titles()

    parts = [
        f"제목: {title}",
        f"플랫폼: {clean_value(row.get('platform', ''), 'platform')}",
        f"핵심 키워드: {keyword}",
        f"구조 타입: {plan['variant']['name']}",
        f"주제 프로필: {profile['name']}",
        "",
        "=" * 50,
        f"1. {section_titles[0]}",
        "=" * 50,
        render_intro(keyword, profile, plan),
        "",
        "=" * 50,
        f"2. {section_titles[1]}",
        "=" * 50,
        render_principles(keyword, profile, plan),
    ]

    variant_name = plan["variant"]["name"]

    if variant_name == "workflow_playbook":
        parts.extend(
            [
                "",
                "=" * 50,
                "3. 실행 전 점검 항목",
                "=" * 50,
                render_preparation(keyword, profile, plan),
            ]
        )
        scenario_section_number = 4
    else:
        scenario_section_number = 3

    parts.extend(
        [
            "",
            "=" * 50,
            f"{scenario_section_number}. {section_titles[2]}",
            "=" * 50,
        ]
    )

    for index, scenario in enumerate(plan["scenarios"]):
        if variant_name == "checklist_review":
            parts.append(render_checklist_item(keyword, profile, plan, scenario, index))
        elif variant_name == "comparison_guide":
            parts.append(render_comparison_item(keyword, profile, plan, scenario, index))
        elif variant_name == "quickstart_entry":
            parts.append(render_quickstart_item(keyword, profile, plan, scenario, index))
        else:
            parts.append(render_scenario(keyword, profile, plan, scenario, index))

    review_section_number = scenario_section_number + 1
    qna_section_number = review_section_number + 1
    conclusion_section_number = qna_section_number + 1

    parts.extend(
        [
            "",
            "=" * 50,
            f"{review_section_number}. {section_titles[3]}",
            "=" * 50,
            render_review_or_exception(keyword, profile, plan),
            "",
            "=" * 50,
            f"{qna_section_number}. {section_titles[4]}",
            "=" * 50,
            render_qna(keyword, profile, plan),
            "",
            "=" * 50,
            f"{conclusion_section_number}. 정리",
            "=" * 50,
            render_conclusion(keyword, profile, plan),
        ]
    )

    article = "\n\n".join(part for part in parts if part is not None).strip()
    korean_count = count_korean_content_chars(article)
    if korean_count < MIN_KOREAN_CONTENT_CHARS:
        raise ValueError(
            f"Generated article has only {korean_count} Korean content characters; "
            f"requires at least {MIN_KOREAN_CONTENT_CHARS}."
        )
    return article


def render_article_locally_v2(row, plan):
    title = plan["title"]
    keyword = plan["keyword"]
    profile = plan["profile"]
    section_titles = get_required_section_titles()
    variant_name = plan["variant"]["name"]

    parts = [
        f"제목: {title}",
        f"플랫폼: {clean_value(row.get('platform', ''), 'platform')}",
        f"핵심 키워드: {keyword}",
        f"구조 타입: {plan['variant']['name']}",
        f"주제 프로필: {profile['name']}",
        "",
        "=" * 50,
        f"1. {section_titles[0]}",
        "=" * 50,
        render_intro(keyword, profile, plan),
        "",
        "=" * 50,
        f"2. {section_titles[1]}",
        "=" * 50,
        render_principles(keyword, profile, plan),
        "",
        "=" * 50,
        f"3. {section_titles[2]}",
        "=" * 50,
    ]

    if variant_name == "workflow_playbook":
        parts.append(render_preparation(keyword, profile, plan))

    for index, scenario in enumerate(plan["scenarios"]):
        if variant_name == "checklist_review":
            parts.append(render_checklist_item(keyword, profile, plan, scenario, index))
        elif variant_name == "comparison_guide":
            parts.append(render_comparison_item(keyword, profile, plan, scenario, index))
        elif variant_name == "quickstart_entry":
            parts.append(render_quickstart_item(keyword, profile, plan, scenario, index))
        else:
            parts.append(render_scenario(keyword, profile, plan, scenario, index))

    parts.extend(
        [
            render_review_or_exception(keyword, profile, plan),
            "",
            "=" * 50,
            f"4. {section_titles[3]}",
            "=" * 50,
            render_qna(keyword, profile, plan),
            "",
            "=" * 50,
            f"5. {section_titles[4]}",
            "=" * 50,
            render_conclusion(keyword, profile, plan),
        ]
    )

    article = "\n\n".join(part for part in parts if part is not None).strip()
    korean_count = count_korean_content_chars(article)
    if korean_count < MIN_KOREAN_CONTENT_CHARS:
        raise ValueError(
            f"Generated article has only {korean_count} Korean content characters; "
            f"requires at least {MIN_KOREAN_CONTENT_CHARS}."
        )
    return article


_SCENARIO_LABEL = {
    "problem_solution": "오류가 발생하는 실제 상황",
    "workflow_playbook": "단계별로 다룰 작업 상황",
    "standardization_blueprint": "표준화가 필요한 실제 상황",
    "decision_guide": "판단이 필요한 실제 상황",
    "checklist_review": "점검 과정에서 나오는 실제 사례",
    "comparison_guide": "직접 비교할 실제 상황",
    "quickstart_entry": "처음 사용할 때 마주치는 상황",
}


def generate_article_via_api(row, plan):
    if not PERPLEXITY_API_KEY:
        return None

    keyword = plan["keyword"]
    profile = plan["profile"]
    section_titles = get_required_section_titles()
    variant_name = plan["variant"]["name"]
    scenario_label = _SCENARIO_LABEL.get(variant_name, "다룰 실제 상황")

    prompt = f"""다음 조건을 모두 지켜 블로그 글을 작성해줘.

제목: {plan["title"]}
핵심 키워드: {keyword}
플랫폼: {clean_value(row.get("platform", ""), "platform")}
주제 프로필: {profile["name"]}
작업 흐름 핵심: {profile["workflow"]}
핵심 화면 요소: {", ".join(profile["surfaces"])}
{scenario_label}:
- {plan["scenarios"][0]}
- {plan["scenarios"][1]}
- {plan["scenarios"][2]}

[필수 규칙]
1. 한글 본문 글자 수만 최소 {MIN_KOREAN_CONTENT_CHARS:,}자 이상이어야 한다.
2. 영어, 숫자, 기호는 글자 수 계산에서 제외한다.
3. 목록, 표, 코드, 이미지 설명, 섹션 제목은 글자 수 계산에서 제외한다.
4. 한국어 문단 뒤에 대응되는 영어 문단을 바로 붙일 것
5. 섹션 순서:
   - 1. 서론
   - 2. 본문 1: 개념 설명
   - 3. 본문 2: 실무 적용 + 단계별 설명
   - 4. Q&A
   - 5. 결론
5-1. 각 섹션 제목은 위 문구를 그대로 사용하고, 다른 표현으로 바꾸지 않습니다.
6. 예제는 정확히 3개, Q&A는 정확히 5개
7. 다른 주제 글과 헷갈리지 않도록 {profile["surfaces"]}와 {profile["assets"]}처럼 주제에 맞는 용어를 적극 사용할 것
8. 절대로 "상단 메뉴 -> 관련 탭 -> 설정 창" 같은 범용 문장을 반복하지 말고, 실제 주제에 맞는 화면 흐름으로 구체화할 것
9. 추상적인 생산성 설명보다 작업 기준, 적용 범위, 검토 순서, 예외 처리 기준을 더 강조할 것
10. 아래 위험 요소를 피하는 방법을 자연스럽게 포함할 것: {", ".join(profile["pitfalls"])}

출력은 완성된 본문만 보여줘.
"""

    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "sonar",
        "messages": [{"role": "user", "content": prompt}],
    }

    for _ in range(API_MAX_ATTEMPTS):
        try:
            response = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers,
                json=body,
                timeout=API_TIMEOUT_SECONDS,
            )
        except Exception:
            continue

        if response.status_code != 200:
            continue

        text = response.json()["choices"][0]["message"]["content"]
        if count_korean_content_chars(text) >= MIN_KOREAN_CONTENT_CHARS:
            return text

    return None


def generate_draft_via_codex(row, plan):
    """1단계: gpt-4o로 1차 초안 생성."""
    if not OPENAI_API_KEY:
        return None

    keyword = plan["keyword"]
    profile = plan["profile"]
    section_titles = plan["variant"]["section_titles"]
    scenario_label = _SCENARIO_LABEL.get(plan["variant"]["name"], "다룰 실제 상황")

    prompt = f"""당신은 실무 블로그 글 작성 전문가입니다.

제목: {plan["title"]}
핵심 키워드: {keyword}
플랫폼: {clean_value(row.get("platform", ""), "platform")}
주제 프로필: {profile["name"]}
작업 흐름: {profile["workflow"]}
주요 화면 요소: {", ".join(profile["surfaces"])}
{scenario_label}:
- {plan["scenarios"][0]}
- {plan["scenarios"][1]}
- {plan["scenarios"][2]}

[필수 규칙]
1. 한국어 본문 글자 수 최소 {MIN_KOREAN_CONTENT_CHARS:,}자 이상 (영어·숫자·기호·제목 제외)
2. 각 한국어 문단 바로 다음에 대응하는 영어 문단을 붙일 것
3. 섹션 순서: 1. 서론 → 2. 본문 1: 개념 설명 → 3. 본문 2: 실무 적용 + 단계별 설명 → 4. Q&A → 5. 결론
4. 각 섹션 제목은 위 문구를 그대로 사용하고 바꾸지 않습니다.
5. 제시된 상황은 정확히 3개, Q&A는 정확히 5개
6. 범용적인 "메뉴 → 탭 → 설정" 패턴 금지, 주제 특화 용어 사용
7. 다음 위험 요소를 자연스럽게 포함: {", ".join(profile["pitfalls"])}

본문만 출력하세요."""

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}], "max_tokens": 4096},
            timeout=120,
        )
        if response.status_code != 200:
            print(f"[codex] status={response.status_code}", flush=True)
            return None
        text = response.json()["choices"][0]["message"]["content"]
        if count_korean_content_chars(text) >= MIN_KOREAN_CONTENT_CHARS:
            return text
    except Exception as e:
        print(f"[codex] error: {e}", flush=True)
    return None


def refine_article_via_claude(draft, plan):
    """2단계: Claude로 문법·자연스러움 수정. 내용은 유지."""
    if not ANTHROPIC_API_KEY or not draft:
        return draft

    keyword = plan["keyword"]
    prompt = f"""아래 블로그 글 초안을 검토하고 수정해주세요.

수정 기준:
1. 문법 오류 수정
2. 어색한 한국어/영어 표현을 자연스럽게 개선
3. 문단 간 흐름이 매끄럽게 이어지도록 수정
4. 키워드 "{keyword}"의 맥락 일관성 유지
5. 내용·구조·길이는 절대 변경하지 말 것

원문:
{draft}

수정된 본문만 출력하세요."""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"model": "claude-sonnet-4-6", "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        if response.status_code != 200:
            print(f"[claude-refine] status={response.status_code}", flush=True)
            return draft
        text = response.json()["content"][0]["text"]
        if count_korean_content_chars(text) >= MIN_KOREAN_CONTENT_CHARS:
            return text
    except Exception as e:
        print(f"[claude-refine] error: {e}", flush=True)
    return draft


def restore_english_paragraphs_via_claude(article, plan):
    if not ANTHROPIC_API_KEY or not article:
        return article

    keyword = plan["keyword"]
    prompt = f"""아래 블로그 글은 반드시 한글 문단 다음에 대응되는 영어 문단이 바로 붙는 상하 병렬 구조여야 합니다.

수정 목표:
1. 영어 문단이 빠진 모든 한글 문단 뒤에 대응되는 영어 문단을 추가합니다.
2. 기존 한글 문단의 의미, 순서, 섹션 구조는 유지합니다.
3. 제목, 예제 개수, Q&A 개수는 바꾸지 않습니다.
4. 출력은 수정된 전체 본문만 반환합니다.
5. 모든 한글 본문 문단 뒤에는 영어 문단이 바로 와야 합니다.

키워드: {keyword}

본문:
{article}
"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"model": "claude-sonnet-4-6", "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        if response.status_code != 200:
            print(f"[claude-bilingual] status={response.status_code}", flush=True)
            return article
        text = response.json()["content"][0]["text"]
        if count_korean_content_chars(text) >= MIN_KOREAN_CONTENT_CHARS and has_required_bilingual_structure(text):
            return text
    except Exception as e:
        print(f"[claude-bilingual] error: {e}", flush=True)
    return article


def enforce_bilingual_article(article, row, plan):
    if has_required_bilingual_structure(article):
        return article, "ok"

    restored = restore_english_paragraphs_via_claude(article, plan)
    if restored != article and has_required_bilingual_structure(restored):
        return restored, "claude_restore"

    local_article = render_article_locally_v2(row, plan)
    if has_required_bilingual_structure(local_article):
        return local_article, "local_regen"

    return article, "failed"


def enforce_required_article_structure(article, row, plan):
    if has_required_article_structure(article):
        return article, "ok"

    local_article = render_article_locally_v2(row, plan)
    if has_required_article_structure(local_article):
        return local_article, "local_regen"

    return article, "failed"


def verify_article_via_perplexity(article, plan):
    """3단계: Perplexity로 사실 정확성 + 중복 검증.
    Returns: {"pass": bool, "corrections": str, "reason": str}
    """
    if not PERPLEXITY_API_KEY:
        return {"pass": True, "corrections": "", "reason": "API 없음 — 통과"}

    keyword = plan["keyword"]
    excerpt = article[:2000]

    prompt = f"""당신은 블로그 콘텐츠 검수 전문가입니다.
아래 글을 두 가지 기준으로 검수하세요.

[검수 대상]
제목: {plan["title"]}
키워드: {keyword}

본문 (앞부분):
{excerpt}

[검수 기준]
1. 사실 정확성: 잘못된 정보, 틀린 수치, 부정확한 기술 설명
2. 중복/표절: 인터넷에 이미 있는 내용을 그대로 나열한 수준

반드시 아래 JSON만 출력하세요. 설명 없이 JSON만.

{{
  "pass": true | false,
  "corrections": "수정이 필요한 내용 구체적 설명 (없으면 빈 문자열)",
  "reason": "검수 결과 한 줄 요약"
}}

판단 기준: 명백한 사실 오류가 없고 독창성이 있으면 pass true, 사실 오류나 심각한 중복이면 pass false."""

    try:
        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"},
            json={"model": "sonar", "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        if response.status_code != 200:
            return {"pass": True, "corrections": "", "reason": "API 오류 — 통과 처리"}
        text = response.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            result = json.loads(match.group(0))
            if "pass" in result:
                return result
    except Exception as e:
        print(f"[perplexity-verify] error: {e}", flush=True)
    return {"pass": True, "corrections": "", "reason": "파싱 실패 — 통과 처리"}


def apply_corrections_via_claude(article, corrections, plan):
    """4단계: Perplexity 지적 사항을 Claude로 적용."""
    if not ANTHROPIC_API_KEY or not corrections:
        return article

    keyword = plan["keyword"]
    prompt = f"""아래 블로그 글에 검수 의견을 반영해 수정해주세요.

[검수 의견]
{corrections}

[원문]
{article}

수정 기준:
- 검수 의견에서 지적한 사항만 수정
- 나머지 내용·구조·길이는 그대로 유지
- 키워드 "{keyword}" 맥락 유지

수정된 본문만 출력하세요."""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"model": "claude-sonnet-4-6", "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        if response.status_code != 200:
            print(f"[claude-fix] status={response.status_code}", flush=True)
            return article
        text = response.json()["content"][0]["text"]
        if count_korean_content_chars(text) >= MIN_KOREAN_CONTENT_CHARS:
            return text
    except Exception as e:
        print(f"[claude-fix] error: {e}", flush=True)
    return article


def run_article_pipeline(row, plan):
    """
    5단계 파이프라인:
      1. Codex(gpt-4o) 1차 초안
      2. Claude 문법·자연스러움 수정
      3. Perplexity 사실 정확성 + 중복 검증
      4. (실패 시) Claude 수정 사항 적용
      5. Perplexity 재검증 (최대 PIPELINE_VERIFY_RETRIES회)

    Returns: (article_text, source_label)
    """
    keyword = clean_value(row.get("keyword", ""), "")

    # 1단계: Codex 초안
    print(f"[pipeline:1] codex draft keyword={keyword}", flush=True)
    draft = generate_draft_via_codex(row, plan)
    if draft:
        source = "codex"
    else:
        print(f"[pipeline:1] codex failed → local render", flush=True)
        draft = render_article_locally_v2(row, plan)
        source = "local"

    # 2단계: Claude 다듬기
    print(f"[pipeline:2] claude refine source={source}", flush=True)
    article = refine_article_via_claude(draft, plan)
    if article != draft:
        source = f"{source}+claude"
    article, bilingual_stage = enforce_bilingual_article(article, row, plan)
    if bilingual_stage == "claude_restore":
        source = f"{source}+bilingual"
    elif bilingual_stage == "local_regen":
        source = "local+bilingual"
    article, structure_stage = enforce_required_article_structure(article, row, plan)
    if structure_stage == "local_regen":
        source = "local+structure"

    # 3~5단계: Perplexity 검증 루프
    for verify_num in range(PIPELINE_VERIFY_RETRIES):
        print(f"[pipeline:3] perplexity verify attempt={verify_num + 1}", flush=True)
        result = verify_article_via_perplexity(article, plan)
        reason = result.get("reason", "")

        if result.get("pass"):
            print(f"[pipeline:3] verify passed reason={reason}", flush=True)
            break

        corrections = result.get("corrections", "")
        print(f"[pipeline:4] claude fix attempt={verify_num + 1} corrections={corrections[:80]}", flush=True)

        if verify_num < PIPELINE_VERIFY_RETRIES - 1:
            article = apply_corrections_via_claude(article, corrections, plan)
            article, bilingual_stage = enforce_bilingual_article(article, row, plan)
            article, structure_stage = enforce_required_article_structure(article, row, plan)
            source = f"{source}+fix{verify_num + 1}"
            if bilingual_stage == "claude_restore":
                source = f"{source}+bilingual"
            elif bilingual_stage == "local_regen":
                source = "local+bilingual"
            if structure_stage == "local_regen":
                source = "local+structure"
        else:
            print(f"[pipeline] max verify retries reached, using current version", flush=True)

    article, bilingual_stage = enforce_bilingual_article(article, row, plan)
    article, structure_stage = enforce_required_article_structure(article, row, plan)
    if bilingual_stage == "claude_restore":
        source = f"{source}+bilingual"
    elif bilingual_stage == "local_regen":
        source = "local+bilingual"
    if structure_stage == "local_regen":
        source = "local+structure"
    return article, source


def _timed(seconds: float) -> str:
    return f"{seconds:.1f}s"


def _limit_topics_for_run(df, source):
    if df.empty:
        return df
    if len(df) <= MAX_TOPICS_PER_RUN:
        return df

    limited = df.head(MAX_TOPICS_PER_RUN).copy()
    print(
        f"[speed] limiting topics for this run: {len(df)} -> {len(limited)} "
        f"(source={source}, BLOGAUTO_MAX_TOPICS_PER_RUN={MAX_TOPICS_PER_RUN})"
    )
    return limited


def create_ai_article(row, attempt=0, run_state=None, file_index=0):
    plan = build_article_plan(row, attempt, run_state=run_state, file_index=file_index)
    used_api = bool(PERPLEXITY_API_KEY) and (attempt == 0 or USE_API_ON_RETRY)
    started_at = time.perf_counter()
    api_result = generate_article_via_api(row, plan) if used_api else None
    api_elapsed = time.perf_counter() - started_at
    article_source = "api" if api_result else "local"
    article = api_result or render_article_locally_v2(row, plan)
    article, bilingual_stage = enforce_bilingual_article(article, row, plan)
    article, structure_stage = enforce_required_article_structure(article, row, plan)
    if bilingual_stage == "claude_restore":
        article_source = f"{article_source}+bilingual"
    elif bilingual_stage == "local_regen":
        article_source = "local+bilingual"
    if structure_stage == "local_regen":
        article_source = "local+structure"
    return article, plan, article_source, api_elapsed


def load_pending_topics_v2():
    from topic_registry import TOPIC_USED_PATH, normalize, read_csv_safe

    if QUEUE_PATH.exists():
        df = pd.read_csv(QUEUE_PATH, encoding="utf-8-sig")
        if not df.empty and "status" in df.columns:
            pending = df[df["status"] == "pending"].copy()
            if not pending.empty:
                print(f"writing_queue.csv queue pending rows: {len(pending)}")
                return _limit_topics_for_run(pending, "queue"), "queue"

            drafted = df[df["status"] == "drafted"].copy()
            if ALLOW_DRAFTED_FALLBACK and not drafted.empty:
                print(f"writing_queue.csv fallback drafted rows: {len(drafted)}")
                return _limit_topics_for_run(drafted, "queue_drafted"), "queue_drafted"

    if TOP10_PATH.exists():
        df = pd.read_csv(TOP10_PATH, encoding="utf-8-sig")
        if not df.empty:
            used_df = read_csv_safe(TOPIC_USED_PATH)
            if not used_df.empty and "keyword" in used_df.columns:
                used_keys = {normalize(k) for k in used_df["keyword"].dropna().astype(str)}
                df = df[~df["keyword"].astype(str).map(normalize).isin(used_keys)].copy()

            if df.empty:
                print("topic_top10.csv has no remaining topics after filtering.")
                return pd.DataFrame(), None

            print(f"topic_top10.csv fallback rows: {len(df)}")
            return _limit_topics_for_run(df, "top10"), "top10"

    return pd.DataFrame(), None


def create_output_run_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    day_prefix = datetime.now().strftime("%Y-%m-%d")
    run_index = 1

    while True:
        candidate = OUTPUT_DIR / f"{day_prefix}_{run_index}"
        if not candidate.exists():
            print(f"[debug] output run dir candidate: {candidate}")
            candidate.mkdir(parents=True, exist_ok=False)
            print(f"[debug] output run dir created: {candidate}")
            return candidate
        run_index += 1


def _build_similarity_row(row, plan, attempt, status, match, structural_match=None):
    candidate = match.candidate
    structural_score = structural_match.score if structural_match else 0.0
    if status == "accepted":
        if (
            match.score >= SIMILARITY_REVIEW_THRESHOLD
            or structural_score >= STRUCTURAL_REVIEW_THRESHOLD
        ):
            decision = "review"
            if (
                match.score >= SIMILARITY_REVIEW_THRESHOLD
                and structural_score >= STRUCTURAL_REVIEW_THRESHOLD
            ):
                reason = "accepted in near-threshold similarity and structural review band"
            elif match.score >= SIMILARITY_REVIEW_THRESHOLD:
                reason = "accepted in near-threshold similarity review band"
            else:
                reason = "accepted in near-threshold structural review band"
        else:
            decision = "pass"
            reason = "passed similarity and structural thresholds"
    elif status == "retry":
        decision = "review"
        if match.score >= SIMILARITY_THRESHOLD and structural_score >= STRUCTURAL_THRESHOLD:
            reason = "standard and structural similarity above threshold"
        elif match.score >= SIMILARITY_THRESHOLD:
            reason = "standard similarity above threshold"
        elif structural_score >= STRUCTURAL_THRESHOLD:
            reason = "structural similarity above threshold"
        else:
            reason = "quality penalty retry"
    else:
        decision = "block"
        if match.score >= SIMILARITY_THRESHOLD and structural_score >= STRUCTURAL_THRESHOLD:
            reason = "blocked by standard and structural similarity"
        elif match.score >= SIMILARITY_THRESHOLD:
            reason = "blocked by standard similarity"
        elif structural_score >= STRUCTURAL_THRESHOLD:
            reason = "blocked by structural similarity"
        else:
            reason = "blocked after retry exhaustion"
    return {
        "keyword": clean_value(row.get("keyword", ""), ""),
        "title": clean_value(row.get("title", ""), ""),
        "profile": plan["profile"]["name"],
        "structure_variant": plan["variant"]["name"],
        "attempt": attempt,
        "status": status,
        "decision": decision,
        "reason": reason,
        "similarity_score": match.score,
        "structural_score": structural_match.score if structural_match else "",
        "block_reason": "structural" if (structural_match and structural_match.score >= STRUCTURAL_THRESHOLD and (not match or match.score < structural_match.score)) else "standard",
        "matched_source": candidate.source if candidate else "",
        "matched_title": candidate.title if candidate else "",
        "matched_url": candidate.url if candidate else "",
        "matched_label": candidate.label if candidate else "",
        "matched_extra": candidate.extra if candidate else "",
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_quality_row(row, plan, quality_meta, match, structural_match, decision, attempt, run_dir):
    return {
        "run_id": run_dir.name if run_dir else "",
        "topic_id": clean_value(row.get("topic_id", ""), ""),
        "platform": clean_value(row.get("platform", ""), ""),
        "title": plan["title"],
        "keyword": clean_value(row.get("keyword", ""), ""),
        "structure_slot": quality_meta["structure_slot"],
        "lead_slot": quality_meta["lead_slot"],
        "rhythm_slot": quality_meta["rhythm_slot"],
        "style_slot": quality_meta["style_slot"],
        "ending_slot": quality_meta["ending_slot"],
        "transition_signature": quality_meta["transition_signature"],
        "avg_sentence_length": quality_meta["avg_sentence_length"],
        "paragraph_count": quality_meta["paragraph_count"],
        "penalty_structure": quality_meta["penalty_structure"],
        "penalty_rhythm": quality_meta["penalty_rhythm"],
        "penalty_style": quality_meta["penalty_style"],
        "penalty_transition": quality_meta["penalty_transition"],
        "penalty_ending": quality_meta["penalty_ending"],
        "penalty_duplication_soft": quality_meta["penalty_duplication_soft"],
        "total_penalty": quality_meta["total_penalty"],
        "best_similarity_score": match.score,
        "best_structural_score": structural_match.score if structural_match else "",
        "decision": decision,
        "decision_reason": quality_meta["decision_reason"],
        "rewrite_attempt": attempt,
        "article_source": quality_meta.get("article_source", ""),
        "api_elapsed_seconds": quality_meta.get("api_elapsed_seconds", ""),
        "attempt_elapsed_seconds": quality_meta.get("attempt_elapsed_seconds", ""),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _generate_validated_article_v2(row, checker, report_rows, quality_rows, run_dir, run_state=None, file_index=0):
    keyword = clean_value(row.get("keyword", ""), "제목 없음")
    for attempt in range(MAX_REWRITE_ATTEMPTS):
        attempt_started_at = time.perf_counter()
        article_text, plan, article_source, api_elapsed = create_ai_article(
            row, attempt=attempt, run_state=run_state, file_index=file_index
        )
        match, structural_match, heading_match = checker.find_best_matches(article_text)
        quality_meta = evaluate_quality(plan, article_text, match, structural_match, run_state=run_state)
        attempt_elapsed = time.perf_counter() - attempt_started_at
        quality_meta["article_source"] = article_source
        quality_meta["api_elapsed_seconds"] = round(api_elapsed, 3)
        quality_meta["attempt_elapsed_seconds"] = round(attempt_elapsed, 3)
        bilingual_meta = analyze_bilingual_structure(article_text)
        required_structure_meta = analyze_required_article_structure(article_text)

        is_standard_ok = match.score < SIMILARITY_THRESHOLD
        is_structural_ok = structural_match.score < STRUCTURAL_THRESHOLD
        is_heading_ok = heading_match.score < checker.heading_threshold
        is_quality_ok = quality_meta["total_penalty"] < QUALITY_PENALTY_THRESHOLD
        is_bilingual_ok = bilingual_meta["is_bilingual"]
        is_required_structure_ok = (
            required_structure_meta["has_required_sections"]
            and required_structure_meta["has_required_scenarios"]
            and required_structure_meta["has_required_qas"]
        )
        required_section_preview = required_structure_meta["found_section_titles"][:5]

        print(
            f"[attempt] keyword={keyword} "
            f"attempt={attempt + 1}/{MAX_REWRITE_ATTEMPTS} "
            f"source={article_source} api={_timed(api_elapsed)} total={_timed(attempt_elapsed)} "
            f"standard={match.score} structural={structural_match.score} "
            f"heading={heading_match.score} penalty={quality_meta['total_penalty']} "
            f"bilingual={bilingual_meta['paired_blocks']}/{bilingual_meta['korean_blocks']} "
            f"required=sections:{required_section_preview} scenarios:{required_structure_meta['unique_scenarios']} qas:{required_structure_meta['unique_qas']}"
        )

        if (
            is_standard_ok
            and is_structural_ok
            and is_heading_ok
            and is_quality_ok
            and is_bilingual_ok
            and is_required_structure_ok
        ):
            register_plan_usage(plan, run_state)
            save_qa_used(plan["profile"]["name"], plan["questions"])
            report_rows.append(_build_similarity_row(row, plan, attempt + 1, "accepted", match, structural_match))
            quality_rows.append(_build_quality_row(row, plan, quality_meta, match, structural_match, "accepted", attempt + 1, run_dir))
            print(
                f"[accepted] keyword={keyword} "
                f"attempt={attempt + 1} source={article_source} total={_timed(attempt_elapsed)}"
            )
            return article_text, plan, match, structural_match, quality_meta

        report_rows.append(_build_similarity_row(row, plan, attempt + 1, "retry", match, structural_match))
        retry_decision = "quality_penalty" if is_standard_ok and is_structural_ok and is_heading_ok and not is_quality_ok else "similarity_retry"
        quality_rows.append(_build_quality_row(row, plan, quality_meta, match, structural_match, retry_decision, attempt + 1, run_dir))
        failed_checks = []
        if not is_standard_ok:
            failed_checks.append("similarity")
        if not is_structural_ok:
            failed_checks.append("structural")
        if not is_quality_ok:
            failed_checks.append("quality_penalty")
        if not is_bilingual_ok:
            failed_checks.append("bilingual_required")
        if not is_required_structure_ok:
            failed_checks.append("required_structure")
        print(
            f"[?좎궗???ъ떆?? {clean_value(row.get('keyword', ''), '')} "
            f"attempt={attempt + 1} standard={match.score} structural={structural_match.score} penalty={quality_meta['total_penalty']}"
        )

        print(
            f"[retry] keyword={keyword} "
            f"attempt={attempt + 1} reason={','.join(failed_checks) or 'unknown'} "
            f"source={article_source} total={_timed(attempt_elapsed)} "
            f"standard={match.score} structural={structural_match.score} penalty={quality_meta['total_penalty']}"
        )

    report_rows.append(_build_similarity_row(row, plan, MAX_REWRITE_ATTEMPTS, "blocked", match, structural_match))
    quality_rows.append(_build_quality_row(row, plan, quality_meta, match, structural_match, "blocked", MAX_REWRITE_ATTEMPTS, run_dir))
    print(f"[blocked] keyword={keyword} attempts={MAX_REWRITE_ATTEMPTS}")
    return None, plan, match, structural_match, quality_meta


def main():
    generate_articles_df()


def _parallel_article_worker(row, checker, run_dir, run_state, file_index):
    """병렬 실행 워커: API 호출은 병렬, 상태 접근(_state_lock)은 직렬화."""
    keyword = clean_value(row.get("keyword", ""), "")
    local_report = []
    local_quality = []
    plan = None
    match = None
    structural_match = None
    quality_meta = {}

    for attempt in range(MAX_REWRITE_ATTEMPTS):
        attempt_started_at = time.perf_counter()

        # 플랜 빌드 - run_state 읽기 직렬화
        with _state_lock:
            plan = build_article_plan(row, attempt, run_state=run_state, file_index=file_index)

        # 파이프라인 실행 - 잠금 없이 병렬 실행 (병목 구간)
        print(f"[pipeline] keyword={keyword} attempt={attempt+1}", flush=True)
        pipeline_started = time.perf_counter()
        article_text, article_source = run_article_pipeline(row, plan)
        pipeline_elapsed = time.perf_counter() - pipeline_started
        attempt_elapsed = time.perf_counter() - attempt_started_at

        # 유사도 검사 + 품질 평가 + 상태 갱신 - 직렬화
        with _state_lock:
            match, structural_match, heading_match = checker.find_best_matches(article_text)
            quality_meta = evaluate_quality(plan, article_text, match, structural_match, run_state=run_state)
            quality_meta["article_source"] = article_source
            quality_meta["api_elapsed_seconds"] = round(pipeline_elapsed, 3)
            quality_meta["attempt_elapsed_seconds"] = round(attempt_elapsed, 3)
            bilingual_meta = analyze_bilingual_structure(article_text)
            required_structure_meta = analyze_required_article_structure(article_text)

            is_standard_ok = match.score < SIMILARITY_THRESHOLD
            is_structural_ok = structural_match.score < STRUCTURAL_THRESHOLD
            is_heading_ok = heading_match.score < checker.heading_threshold
            is_quality_ok = quality_meta["total_penalty"] < QUALITY_PENALTY_THRESHOLD
            is_bilingual_ok = bilingual_meta["is_bilingual"]
            is_required_structure_ok = (
                required_structure_meta["has_required_sections"]
                and required_structure_meta["has_required_scenarios"]
                and required_structure_meta["has_required_qas"]
            )
            required_section_preview = required_structure_meta["found_section_titles"][:5]

            print(
                f"[attempt] keyword={keyword} "
                f"attempt={attempt + 1}/{MAX_REWRITE_ATTEMPTS} "
                f"source={article_source} pipeline={_timed(pipeline_elapsed)} total={_timed(attempt_elapsed)} "
                f"standard={match.score} structural={structural_match.score} "
                f"heading={heading_match.score} penalty={quality_meta['total_penalty']} "
                f"bilingual={bilingual_meta['paired_blocks']}/{bilingual_meta['korean_blocks']} "
                f"required=sections:{required_section_preview} scenarios:{required_structure_meta['unique_scenarios']} qas:{required_structure_meta['unique_qas']}"
            )

            if (
                is_standard_ok
                and is_structural_ok
                and is_heading_ok
                and is_quality_ok
                and is_bilingual_ok
                and is_required_structure_ok
            ):
                # 잠금 상태에서 즉시 checker에 추가 → 이후 병렬 워커가 중복 감지 가능
                checker.add_candidate("current_run", plan["title"], article_text, extra="")
                register_plan_usage(plan, run_state)
                save_qa_used(plan["profile"]["name"], plan["questions"])
                local_report.append(_build_similarity_row(row, plan, attempt + 1, "accepted", match, structural_match))
                local_quality.append(_build_quality_row(row, plan, quality_meta, match, structural_match, "accepted", attempt + 1, run_dir))
                print(f"[accepted] keyword={keyword} attempt={attempt + 1} source={article_source} pipeline={_timed(pipeline_elapsed)} total={_timed(attempt_elapsed)}")
                return article_text, plan, match, structural_match, quality_meta, local_report, local_quality

            local_report.append(_build_similarity_row(row, plan, attempt + 1, "retry", match, structural_match))
            retry_decision = "quality_penalty" if is_standard_ok and is_structural_ok and is_heading_ok and not is_quality_ok else "similarity_retry"
            local_quality.append(_build_quality_row(row, plan, quality_meta, match, structural_match, retry_decision, attempt + 1, run_dir))
            failed_checks = []
            if not is_standard_ok:
                failed_checks.append("similarity")
            if not is_structural_ok:
                failed_checks.append("structural")
            if not is_heading_ok:
                failed_checks.append("heading")
            if not is_quality_ok:
                failed_checks.append("quality_penalty")
            if not is_bilingual_ok:
                failed_checks.append("bilingual_required")
            if not is_required_structure_ok:
                failed_checks.append("required_structure")
            print(
                f"[retry] keyword={keyword} "
                f"attempt={attempt + 1} reason={','.join(failed_checks) or 'unknown'} "
                f"source={article_source} total={_timed(attempt_elapsed)} "
                f"standard={match.score} structural={structural_match.score} "
                f"heading={heading_match.score} penalty={quality_meta['total_penalty']}"
            )

    with _state_lock:
        local_report.append(_build_similarity_row(row, plan, MAX_REWRITE_ATTEMPTS, "blocked", match, structural_match))
        local_quality.append(_build_quality_row(row, plan, quality_meta, match, structural_match, "blocked", MAX_REWRITE_ATTEMPTS, run_dir))
        print(f"[blocked] keyword={keyword} attempts={MAX_REWRITE_ATTEMPTS}")

    return None, plan, match, structural_match, quality_meta, local_report, local_quality


def _save_article_file(row, plan, quality_meta, match, structural_match, article_text, run_dir, file_index):
    platform = clean_value(row.get("platform", "platform"), "platform")
    safe_platform = make_safe_filename(platform)
    safe_title = make_safe_filename(plan["title"])
    file_number = str(file_index).zfill(2)
    final_path = run_dir / f"{file_number}_{safe_platform}_{safe_title}.txt"
    article_text, bilingual_stage = enforce_bilingual_article(article_text, row, plan)
    article_text, structure_stage = enforce_required_article_structure(article_text, row, plan)
    if not has_required_bilingual_structure(article_text):
        raise RuntimeError(f"영문 문단 복원 실패: {plan['title']}")
    if bilingual_stage in {"claude_restore", "local_regen"}:
        quality_meta["article_source"] = f"{quality_meta.get('article_source', '')}+{bilingual_stage}".strip("+")
    if not has_required_article_structure(article_text):
        raise RuntimeError(
            f"필수 구조 누락: {plan['title']} (예제 {REQUIRED_SCENARIO_COUNT}개 / Q&A {REQUIRED_QA_COUNT}개)"
        )
    if structure_stage == "local_regen":
        quality_meta["article_source"] = f"{quality_meta.get('article_source', '')}+structure".strip("+")
    article_text, tags, meta_description = attach_article_metadata(article_text, plan, row)
    final_path.write_text(article_text, encoding="utf-8")

    row_dict = row.to_dict()
    row_dict["title"] = plan["title"]
    row_dict["article_text"] = article_text
    row_dict["tag_keywords"] = ", ".join(tags)
    row_dict["meta_description"] = meta_description
    row_dict["output_path"] = str(final_path)
    row_dict["structure_variant"] = plan["variant"]["name"]
    row_dict["structure_slot"] = quality_meta["structure_slot"]
    row_dict["lead_slot"] = quality_meta["lead_slot"]
    row_dict["rhythm_slot"] = quality_meta["rhythm_slot"]
    row_dict["style_slot"] = quality_meta["style_slot"]
    row_dict["ending_slot"] = quality_meta["ending_slot"]
    row_dict["topic_profile"] = plan["profile"]["name"]
    row_dict["similarity_score"] = match.score
    row_dict["structural_score"] = structural_match.score
    row_dict["total_penalty"] = quality_meta["total_penalty"]
    row_dict["decision"] = "accepted"
    row_dict["decision_reason"] = quality_meta["decision_reason"]
    print(f"저장 완료: {final_path}")
    return row_dict, final_path


def generate_articles_df():
    _t0 = time.perf_counter()
    print(f"[config] rewrite_attempts={MAX_REWRITE_ATTEMPTS} api_attempts={API_MAX_ATTEMPTS} "
          f"api_timeout={API_TIMEOUT_SECONDS}s parallel={PARALLEL_WORKERS} "
          f"min_korean={MIN_KOREAN_CONTENT_CHARS} posts_limit={os.getenv('BLOGAUTO_PREVIOUS_POSTS_LIMIT','(default)')}", flush=True)

    top10_df, source = load_pending_topics_v2()
    if top10_df.empty:
        print("생성할 주제가 없습니다.", flush=True)
        return pd.DataFrame()

    print(f"[topics] {len(top10_df)}건 (source={source})", flush=True)

    run_dir = create_output_run_dir()
    checker = SimilarityChecker(threshold=SIMILARITY_THRESHOLD, structural_threshold=STRUCTURAL_THRESHOLD)
    _tc = time.perf_counter()
    checker.load_defaults()
    print(f"[checker] 로딩 완료: {len(checker.candidates)}개 후보 ({time.perf_counter()-_tc:.1f}초)", flush=True)
    run_state = create_run_state(total_count=len(top10_df))

    saved_count = 0
    processed_rows = []
    report_rows = []
    quality_rows = []

    rows_list = [(i + 1, row) for i, (_, row) in enumerate(top10_df.iterrows())]

    if PARALLEL_WORKERS > 1 and len(rows_list) > 1:
        workers = min(PARALLEL_WORKERS, len(rows_list))
        print(f"[parallel] 병렬 모드 시작: {len(rows_list)}개 주제 / {workers} 워커")

        future_to_info = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for file_index, row in rows_list:
                keyword = clean_value(row.get("keyword", ""), "제목 없음")
                print(f"[submit] file_index={file_index} keyword={keyword}")
                future = executor.submit(
                    _parallel_article_worker, row, checker, run_dir, run_state, file_index
                )
                future_to_info[future] = (file_index, row)

            for future in as_completed(future_to_info):
                file_index, row = future_to_info[future]
                try:
                    article_text, plan, match, structural_match, quality_meta, local_report, local_quality = future.result()
                except Exception as exc:
                    print(f"[error] file_index={file_index} exception={exc}")
                    continue

                report_rows.extend(local_report)
                quality_rows.extend(local_quality)

                if not article_text:
                    print(f"생성 차단: {clean_value(row.get('keyword', ''), '제목 없음')} (score={match.score})")
                    continue

                row_dict, final_path = _save_article_file(row, plan, quality_meta, match, structural_match, article_text, run_dir, file_index)
                # 병렬 워커에서 이미 checker에 추가됨 - 파일 경로만 기록
                processed_rows.append(row_dict)
                saved_count += 1
    else:
        for file_index, row in rows_list:
            topic_started_at = time.perf_counter()
            print(f"[생성 중] {clean_value(row.get('keyword', ''), '제목 없음')}")
            print(f"[debug] row {file_index}/{len(rows_list)} platform={clean_value(row.get('platform', ''), '')}")
            article_text, plan, match, structural_match, quality_meta = _generate_validated_article_v2(
                row, checker, report_rows, quality_rows, run_dir, run_state=run_state, file_index=file_index
            )

            if not article_text:
                print(
                    f"생성 차단: {clean_value(row.get('keyword', ''), '제목 없음')} "
                    f"(score={match.score})"
                )
                print(
                    f"[topic_done] keyword={clean_value(row.get('keyword', ''), '')} "
                    f"status=blocked total={_timed(time.perf_counter() - topic_started_at)}"
                )
                continue

            row_dict, final_path = _save_article_file(row, plan, quality_meta, match, structural_match, article_text, run_dir, file_index)
            checker.add_candidate("current_run", plan["title"], article_text, extra=str(final_path))
            processed_rows.append(row_dict)
            saved_count += 1

    print("[debug] article generation loop completed")
    report_path = save_similarity_report(report_rows, run_dir / "similarity_report.csv")
    print("주제 분기형 완성 글 txt 저장 완료")
    print(f"저장 개수: {saved_count}")
    print(f"저장 위치: {run_dir}")
    print(f"사용 상태: {source}")
    print(f"유사도 리포트: {report_path}")
    quality_log_path = append_quality_log(quality_rows)
    print(f"content quality log: {quality_log_path}")
    return pd.DataFrame(processed_rows)


if __name__ == "__main__":
    main()
