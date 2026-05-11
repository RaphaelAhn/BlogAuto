# BlogAuto

`BlogAuto`는 코드, 작업 데이터, 생성 결과물을 분리해서 관리하도록 정리된 프로젝트입니다.

## 폴더 구조

- `automation/app.py`: Streamlit 실행 진입점
- `automation/scripts/`: 자동화 파이프라인 스크립트 모음
- `automation/data/`: CSV 입력값과 기록용 데이터 파일
- `automation/content/`: 플랫폼별 초안 및 완성 글 저장 폴더
- `automation/output/`: 실행 회차별 최종 결과물 출력 폴더
- `logs/`: 실행 로그 저장 폴더

## 참고 사항

- 공통 경로 상수는 `automation/scripts/paths.py`에서 관리합니다.
- 생성 결과물은 `.gitignore`에 등록되어 있어서 저장소에는 소스 파일 위주로 유지됩니다.
- `check_syntax.bat`를 실행하면 실제 Python 실행기 또는 `uv` 대체 경로를 사용해 문법 검사를 할 수 있습니다.
- 개발 중 빠르게 다시 빌드할 때는 `build_quick.bat`를 사용합니다.
- 배포용으로 깨끗한 전체 빌드를 만들 때는 `build_release.bat`를 사용합니다.
- 빌드 결과물은 `BlogAuto/dist/BlogAuto`에 생성되고, PyInstaller 작업 파일은 `BlogAuto/build/pyinstaller`에 저장됩니다.

## 실행 속도 기본값

- `start_blog_auto.bat`는 실행할 때 아래 속도 정책을 자동으로 적용합니다.
- `BLOGAUTO_MAX_REWRITE_ATTEMPTS=2`
- `BLOGAUTO_API_MAX_ATTEMPTS=1`
- `BLOGAUTO_API_TIMEOUT_SECONDS=45`
- `BLOGAUTO_MAX_TOPICS_PER_RUN=4`
- `BLOGAUTO_INCLUDE_DRAFTED_FALLBACK=false`
- `BLOGAUTO_USE_API_ON_RETRY=false`
- 즉, 기본 실행은 한 번에 너무 많은 글을 오래 재시도하지 않도록 보수적으로 제한되어 있습니다.

## 결과물 저장 방식

- `1회 실행` 기준으로 완성 글은 기본적으로 `12개` 생성됩니다.
- 같은 날 여러 번 실행하면 결과물은 한 날짜 폴더에 섞이지 않고 `회차별 폴더`로 분리됩니다.
- 생성 폴더 이름 형식은 `YYYY-MM-DD_회차` 입니다.
- 예시:
  - `automation/output/2026-05-04_1`
  - `automation/output/2026-05-04_2`
  - `automation/output/2026-05-04_3`

## 다회 실행 기준

- 하루에 `3회` 실행하면 최대 `36개` 글이 생성될 수 있습니다.
- 각 회차의 결과물은 각각 다른 출력 폴더에 저장됩니다.
- `작업 큐 생성`은 이전에 이미 사용한 주제와 의미상 겹치는 항목을 최대한 제외하고 다음 후보를 우선 선택합니다.
- `키워드 후보` 데이터는 다시 참고해도 됩니다.
- `TOP 주제 선정` 데이터도 다시 참고할 수 있지만, 우선순위가 높은 항목부터 먼저 사용합니다.
- 중복 방지 원칙 때문에 충분히 새로운 후보가 없으면 회차별 생성 개수가 `12개보다 적을 수 있습니다.`

## 빌드 업데이트 방법

스크립트를 수정한 뒤 `.exe`에 반영하려면 빌드를 다시 실행해야 합니다.

### 빌드 스크립트 종류

| 스크립트 | 용도 |
|----------|------|
| `build_release.bat` | 배포용 전체 클린 빌드 (권장) |
| `build_quick.bat` | 개발 중 빠른 재빌드 |

### 빌드 실행 순서

1. `BlogAuto/` 폴더 안의 `build_release.bat`을 실행합니다.
   - 또는 상위 폴더의 `build_app.bat`을 실행해도 동일하게 동작합니다.
2. `.venv` 또는 시스템 Python을 자동으로 찾아서 PyInstaller를 실행합니다.
3. 완료되면 `BlogAuto/dist/BlogAuto/BlogAuto.exe`가 생성됩니다.

### 환경변수 설정

`PERPLEXITY_API_KEY`는 빌드 파일에 포함되지 않습니다.  
`.exe` 실행 전에 반드시 환경변수로 등록해야 합니다.

- **일시 설정** (현재 터미널 세션에만 적용):
  ```
  set PERPLEXITY_API_KEY=your-key-here
  ```
- **영구 설정**: Windows 시스템 속성 → 고급 → 환경변수에서 등록

키가 없으면 Perplexity 키워드 수집이 자동으로 건너뛰어지고 터미널에 경고가 출력됩니다.

## 실제 확인 경로

- 소스 실행 기준 결과 폴더: `BlogAuto/automation/output/`
- 빌드 실행 파일 기준 결과 폴더:
  - `BlogAuto/dist/BlogAuto/_internal/automation/output/`
- 실행 파일에서 `오늘 완성 글 폴더 열기` 버튼을 누르면 해당 회차 폴더의 상위 출력 위치를 바로 확인할 수 있습니다.
