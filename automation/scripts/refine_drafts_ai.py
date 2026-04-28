from pathlib import Path
from datetime import datetime
import re
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

TOP10_PATH = DATA_DIR / "topic_top10.csv"


def make_safe_filename(text):
    """Remove characters that cannot be used in Windows file names."""
    text = str(text)
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = text.replace(" ", "_").strip()

    if not text:
        text = "제목_없음"

    return text[:60]


def clean_value(value, fallback=""):
    if pd.isna(value):
        return fallback

    value = str(value).strip()
    return value if value else fallback


def create_ai_article(row):
    """
    Generate a rule-locked blog article.

    Required output rules:
    - Korean/English paragraph-level parallel structure.
    - Fixed sections: introduction, concept, practical steps, Q&A, conclusion.
    - Exactly 3 practical examples.
    - Exactly 5 Q&A items.
    - Long-form text of at least 5,000 characters.
    - Includes menu location, click order, opened window, and option choices.
    """
    platform = clean_value(row.get("platform", "platform"), "platform")
    keyword = clean_value(row.get("keyword", ""), "핵심 기능")
    title = clean_value(row.get("title", ""), f"{keyword} 실무 활용 방법")
    final_score = clean_value(row.get("final_score", ""), "-")

    article = f"""
제목: {title}

플랫폼: {platform}
핵심 키워드: {keyword}
점수: {final_score}

==================================================
1. 서론
==================================================

{keyword}를 검색하는 사람은 보통 단순한 정의보다 바로 해결해야 할 실제 상황을 가지고 있습니다. 업무 문서를 정리해야 하거나, 설정 화면에서 어떤 옵션을 눌러야 할지 막혔거나, 이미 해 본 방법이 제대로 작동하지 않아 다음 순서를 찾고 있을 가능성이 큽니다. 그래서 이 글은 {keyword}를 처음 접하는 사람도 흐름을 놓치지 않도록 왜 필요한지, 어떻게 진행하는지, 언제 쓰는지를 순서대로 설명합니다. 특히 메뉴 위치, 클릭 순서, 열리는 창 이름, 선택해야 할 옵션을 함께 다루어 실제 화면 앞에서 그대로 따라 할 수 있도록 구성합니다. 기능을 아는 것에서 끝나지 않고, 실무에서 실수 없이 적용하는 기준까지 잡는 것이 이 글의 목표입니다.

People who search for {keyword} usually have a real task to solve, not just a need for a short definition. They may need to organize a work document, choose the right option in a settings window, or find the next step after a previous attempt did not work. This article explains why {keyword} is needed, how to use it, and when it is useful in a clear order for first-time readers. It also includes menu locations, click paths, window names, and option choices so the reader can follow the process on the actual screen. The goal is not only to understand the function, but also to apply it safely in practical work.

처음에는 {keyword}가 복잡하게 보일 수 있습니다. 하지만 대부분의 기능은 목적을 먼저 정리하고, 화면에서 들어갈 위치를 확인한 뒤, 작은 예제로 테스트하고, 마지막에 실제 업무 자료에 적용하는 순서로 접근하면 안정적으로 사용할 수 있습니다. 예를 들어 문서 작업이라면 파일을 바로 수정하기 전에 복사본을 만들고, 데이터 작업이라면 원본 범위와 결과 범위를 분리하며, 설정 변경이라면 변경 전 상태를 메모해 두는 것이 좋습니다. 이런 준비는 시간이 오래 걸리는 절차가 아니라, 나중에 되돌리기 어려운 실수를 줄이는 기본 안전장치입니다. 따라서 이 글에서는 기능 자체보다 작업 흐름을 중심으로 설명합니다.

At first, {keyword} may look complicated. However, most features become manageable when you define the purpose first, find the right screen location, test with a small example, and then apply the result to real work material. For document work, it is safer to create a copy before editing the original file; for data work, it is better to separate the source range from the result range; and for setting changes, it is useful to note the previous state before changing options. These preparations are not unnecessary delays, but basic safeguards that reduce mistakes that are hard to reverse later. For that reason, this article focuses on the work process rather than only listing features.

==================================================
2. 본문 1: 개념 설명
==================================================

{keyword}의 핵심은 특정 작업을 더 정확하고 반복 가능하게 만드는 데 있습니다. 단순히 버튼 하나를 누르는 기능처럼 보여도, 실제로는 입력값을 확인하고, 적용 범위를 정하고, 결과를 검토하는 여러 단계가 연결되어 있습니다. 이 개념을 이해하지 못하면 같은 기능을 사용해도 어떤 파일에서는 잘 되고 다른 파일에서는 안 되는 것처럼 느껴질 수 있습니다. 따라서 먼저 지금 해결하려는 문제가 데이터 정리인지, 문서 작성인지, 화면 설정인지, 오류 복구인지 구분해야 합니다. 문제 유형을 구분하면 들어가야 할 메뉴와 선택해야 할 옵션이 훨씬 명확해집니다.

The core idea of {keyword} is to make a specific task more accurate and repeatable. Even if it looks like a simple button or option, it usually includes several connected steps: checking the input, choosing the target range, applying the setting, and reviewing the result. Without this concept, the same feature may seem to work in one file but fail in another. So the first step is to identify whether the problem is about data cleanup, document creation, screen configuration, or error recovery. Once the problem type is clear, the correct menu path and option choices become much easier to identify.

실무에서 {keyword}가 필요한 이유는 시간을 줄이기 위해서만은 아닙니다. 더 중요한 이유는 작업 기준을 일정하게 유지하기 위해서입니다. 같은 업무를 매번 다른 방식으로 처리하면 결과물의 형식이 달라지고, 나중에 다른 사람이 파일을 열었을 때 수정하기 어려워집니다. 반대로 처음부터 메뉴 위치와 클릭 순서를 정해 두면 누구나 같은 방식으로 처리할 수 있습니다. 특히 팀에서 공유하는 문서, 보고서, 템플릿, 데이터 파일은 개인의 감에 의존하기보다 재현 가능한 절차로 관리하는 것이 안전합니다.

In practical work, {keyword} is useful not only because it saves time. The more important reason is that it keeps the work standard consistent. If the same task is handled differently each time, the output format changes and becomes harder for others to edit later. When the menu location and click order are defined from the beginning, anyone can follow the same process. This is especially important for shared documents, reports, templates, and data files, where a repeatable procedure is safer than relying on personal judgment.

사용 시점도 분명히 정해야 합니다. {keyword}는 새 작업을 시작할 때, 기존 작업을 정리할 때, 반복 업무를 표준화할 때, 오류를 점검할 때 특히 효과적입니다. 예를 들어 보고서를 만들기 전에는 형식과 기준을 먼저 정하고, 이미 만들어진 자료를 수정할 때는 원본을 복사한 뒤 필요한 범위만 적용하는 방식이 좋습니다. 오류 해결 상황에서는 한 번에 여러 옵션을 바꾸지 말고, 하나의 설정을 변경한 뒤 결과를 확인해야 원인을 추적할 수 있습니다. 이렇게 사용 시점을 나누면 기능을 무리하게 적용하지 않고 필요한 순간에 정확히 사용할 수 있습니다.

The timing of use also needs to be clear. {keyword} is especially helpful when starting a new task, cleaning up existing work, standardizing repeated tasks, or checking errors. For example, before creating a report, it is better to define the format and rules first; when editing an existing file, it is safer to copy the original and apply the change only to the needed range. In an error-solving situation, you should not change many options at once; instead, change one setting and check the result so the cause can be traced. By separating these use cases, you can apply the feature at the right moment without overusing it.

==================================================
3. 본문 2: 실무 적용 + 단계별 설명
==================================================

실무에서 {keyword}를 적용할 때는 먼저 작업 파일이나 화면을 준비합니다. 원본 자료가 있다면 파일 탐색기에서 해당 파일을 마우스 오른쪽 버튼으로 클릭하고, 복사 버튼을 누른 뒤 같은 폴더에서 붙여넣기를 선택해 백업 파일을 만듭니다. 그다음 프로그램을 실행하고, 상단 메뉴에서 작업과 관련된 탭을 찾습니다. 일반적인 흐름은 파일 열기 → 대상 자료 선택 → 상단 메뉴 선택 → 세부 설정 창 열기 → 옵션 선택 → 미리보기 또는 확인 버튼 클릭 → 결과 검토 순서입니다. 이 순서를 지키면 화면이 달라져도 어떤 단계에서 판단해야 하는지 놓치지 않습니다.

When applying {keyword} in real work, first prepare the file or screen you will use. If there is an original file, right-click the file in File Explorer, click Copy, and then choose Paste in the same folder to create a backup. Then open the program and find the top menu tab related to the task. A common workflow is Open file → Select target material → Choose the top menu → Open the detailed settings window → Select options → Click Preview or OK → Review the result. If you follow this order, you can still understand where to make decisions even when the screen layout changes.

예제 1. 업무 문서에서 {keyword}를 처음 적용하는 상황

상황 설명: 이미 작성된 업무 문서가 있고, 그 안에서 {keyword}를 적용해 형식이나 내용을 정리해야 하는 상황입니다. 이때 가장 먼저 할 일은 원본 문서를 직접 수정하지 않는 것입니다. 파일 탐색기 → 문서가 있는 폴더 → 대상 파일 마우스 오른쪽 클릭 → 복사 → 빈 공간 마우스 오른쪽 클릭 → 붙여넣기 순서로 복사본을 만듭니다. 복사본을 연 뒤 상단 메뉴 → 관련 탭 → 설정 또는 옵션 버튼을 클릭하면 세부 설정 창이 열립니다. 이 창에서 적용 범위는 전체 문서가 아니라 현재 선택 영역 또는 필요한 범위로 지정한 뒤 확인을 누릅니다. 결과가 예상과 다르면 Ctrl+Z로 되돌리고, 적용 범위를 다시 선택한 뒤 같은 순서로 반복합니다.

Example 1. Applying {keyword} for the first time in a work document

Situation: You already have a work document and need to use {keyword} to organize its format or content. The first thing to do is avoid editing the original document directly. In File Explorer, go to the folder that contains the document, right-click the target file, click Copy, right-click an empty area, and click Paste to create a duplicate. Open the copied file, then go to the top menu, choose the related tab, and click Settings or Options to open the detailed settings window. In that window, set the target range to the selected area or the necessary section rather than the whole document, and then click OK. If the result is not what you expected, press Ctrl+Z, select the range again, and repeat the same process.

왜 사용하는지: 이 방식은 원본 손상을 막고, 결과를 보면서 안전하게 조정할 수 있기 때문에 필요합니다. 특히 문서에 표, 이미지, 스타일, 링크가 함께 들어 있는 경우에는 작은 설정 하나가 전체 레이아웃에 영향을 줄 수 있습니다. 복사본에서 먼저 테스트하면 실패해도 업무 자료를 잃지 않습니다. 또한 상단 메뉴와 설정 창을 통해 적용하면 어떤 옵션을 바꿨는지 추적하기 쉽습니다. 같은 업무를 반복해야 할 때도 이 절차를 기록해 두면 다음 작업 시간이 줄어듭니다.

Why this is useful: This method is needed because it protects the original file and allows safe adjustment while checking the result. When a document contains tables, images, styles, and links together, one small setting can affect the entire layout. Testing in a copied file prevents the loss of important work material. Using the top menu and settings window also makes it easier to track which option was changed. If the same task needs to be repeated, recording this procedure reduces the time needed next time.

주의사항: 설정 창이 열렸을 때 기본값을 그대로 누르기 전에 적용 범위를 반드시 확인해야 합니다. 전체 문서, 현재 페이지, 선택 영역, 현재 표처럼 비슷해 보이는 옵션이 있어도 결과는 크게 달라질 수 있습니다. 확인 버튼을 누른 뒤에는 바로 저장하지 말고 화면을 위에서 아래로 훑어 보며 깨진 부분이 없는지 확인합니다. 자동 저장이 켜져 있다면 작업 전 복사본을 만드는 과정이 더 중요합니다. 실무에서는 빠르게 누르는 것보다 되돌릴 수 있는 상태를 먼저 만드는 것이 안전합니다.

Caution: When the settings window opens, always check the target range before accepting the default value. Options such as whole document, current page, selected area, and current table may look similar, but the result can be very different. After clicking OK, do not save immediately; scan the screen from top to bottom and check for broken parts. If autosave is enabled, creating a backup copy before working becomes even more important. In real work, it is safer to prepare a reversible state first than to click quickly.

예제 2. 반복 업무에서 {keyword}를 표준 절차로 만드는 상황

상황 설명: 매주 또는 매월 같은 작업을 반복해야 한다면 {keyword}를 개인 기억에 의존하지 않고 절차로 만들어야 합니다. 먼저 새 문서를 열고, 상단 메뉴 → 파일 → 다른 이름으로 저장을 선택해 템플릿 파일을 만듭니다. 그다음 상단 메뉴 → 관련 탭 → 옵션 또는 설정 버튼을 클릭해 필요한 세부 설정 창을 엽니다. 창 안에서 자주 쓰는 옵션을 선택하고, 적용 범위는 문서 전체 또는 템플릿 전체로 지정합니다. 확인을 누른 뒤 샘플 데이터를 넣어 결과를 검토하고, 문제가 없으면 템플릿을 저장합니다.

Example 2. Turning {keyword} into a standard process for repeated work

Situation: If you repeat the same task every week or month, {keyword} should become a procedure instead of something you remember personally. First, open a new document and choose the top menu → File → Save As to create a template file. Then go to the top menu, choose the related tab, and click Options or Settings to open the detailed settings window. In the window, select the options you use often and set the range to the whole document or the entire template. Click OK, enter sample data, review the result, and save the template if there is no problem.

왜 사용하는지: 반복 업무에서는 결과의 일관성이 가장 중요합니다. 매번 처음부터 설정하면 같은 사람도 날짜나 상황에 따라 다른 선택을 할 수 있습니다. 템플릿으로 만들어 두면 메뉴를 다시 찾는 시간이 줄고, 다른 팀원에게 공유하기도 쉽습니다. 특히 보고서, 체크리스트, 업무 기록, 교육 자료처럼 형식이 중요한 파일은 표준 절차가 있어야 품질이 흔들리지 않습니다. {keyword}를 템플릿에 포함하면 작업 시작 단계부터 기준이 맞춰집니다.

Why this is useful: In repeated work, consistency is the most important point. If you configure everything from the beginning each time, even the same person may choose different options depending on the day or situation. A template reduces the time spent searching menus and makes it easier to share the process with other team members. Files such as reports, checklists, work logs, and training materials need a standard procedure because format quality matters. Including {keyword} in the template aligns the standard from the start of the task.

주의사항: 템플릿에 설정을 저장하기 전에는 실제 데이터가 아니라 샘플 데이터로 먼저 확인해야 합니다. 실제 고객명, 매출, 내부 자료를 넣은 상태로 템플릿을 공유하면 정보 유출 문제가 생길 수 있습니다. 옵션 창에서 기본값으로 저장되는 항목과 현재 파일에만 적용되는 항목도 구분해야 합니다. 저장 후에는 새 파일을 하나 만들어 템플릿이 예상대로 작동하는지 다시 확인합니다. 이 검증까지 끝나야 반복 업무에 사용할 수 있는 표준 파일이라고 볼 수 있습니다.

Caution: Before saving settings in a template, test with sample data instead of real data. If a template is shared with customer names, sales numbers, or internal material inside it, it can create an information leak. You also need to distinguish between options saved as defaults and options applied only to the current file. After saving, create one new file and check again whether the template works as expected. Only after this verification can it be treated as a standard file for repeated work.

예제 3. 오류가 생겼을 때 {keyword}로 원인을 좁히는 상황

상황 설명: 기능이 예상대로 작동하지 않거나 결과가 이상하게 보이면 한 번에 여러 설정을 바꾸지 말고 원인을 좁혀야 합니다. 먼저 현재 화면에서 파일 → 다른 이름으로 저장을 클릭해 점검용 복사본을 만듭니다. 그다음 상단 메뉴 → 관련 탭 → 설정 또는 옵션 버튼을 클릭해 세부 설정 창을 엽니다. 창이 열리면 현재 선택된 옵션을 메모하고, 하나의 옵션만 변경한 뒤 확인을 누릅니다. 결과 화면을 확인하고 문제가 해결되면 변경한 옵션이 원인일 가능성이 높고, 해결되지 않으면 Ctrl+Z 또는 이전 값으로 되돌린 뒤 다음 옵션을 하나씩 확인합니다.

Example 3. Narrowing down an error with {keyword}

Situation: When a feature does not work as expected or the result looks wrong, you should narrow down the cause instead of changing many settings at once. First, choose File → Save As on the current screen and create a copy for testing. Then go to the top menu, choose the related tab, and click Settings or Options to open the detailed settings window. When the window opens, note the currently selected options, change only one option, and click OK. Check the result screen; if the issue is solved, the changed option is likely the cause, and if not, press Ctrl+Z or restore the previous value before checking the next option.

왜 사용하는지: 오류 해결에서 가장 중요한 것은 원인을 추적할 수 있게 만드는 것입니다. 여러 옵션을 동시에 바꾸면 문제가 해결되어도 어떤 설정이 영향을 줬는지 알기 어렵습니다. 반대로 한 번에 하나씩 바꾸면 원인과 결과의 관계가 분명해집니다. 이 방식은 나중에 같은 문제가 다시 생겼을 때 빠르게 대응할 수 있게 해 줍니다. 또한 팀원에게 설명할 때도 “어떤 메뉴에서 어떤 옵션을 바꿨는지”를 정확히 전달할 수 있습니다.

Why this is useful: In error solving, the most important thing is making the cause traceable. If several options are changed at the same time, it becomes difficult to know which setting affected the result even if the problem disappears. When you change one option at a time, the relationship between cause and result becomes clear. This method allows faster response when the same issue appears again later. It also helps you explain exactly which menu and option were changed when sharing the solution with team members.

주의사항: 오류가 났을 때 바로 프로그램을 종료하거나 파일을 덮어쓰면 원인 확인이 어려워집니다. 먼저 화면에 표시된 메시지, 열려 있는 창 이름, 선택된 옵션, 적용 범위를 기록합니다. 가능하면 캡처 도구를 열어 현재 화면을 저장하고, 그다음 하나씩 점검합니다. 외부 파일이나 연결된 데이터가 있는 경우에는 원본 위치가 바뀌었는지도 함께 확인해야 합니다. 실전에서는 문제를 빨리 없애는 것보다 다시 재현하고 설명할 수 있는 상태로 정리하는 것이 더 중요합니다.

Caution: If you close the program immediately or overwrite the file after an error appears, it becomes harder to identify the cause. First, record the message on the screen, the name of the open window, the selected options, and the target range. If possible, open the capture tool and save the current screen before checking each item. If external files or linked data are involved, also check whether the original location has changed. In practice, it is more important to organize the problem so it can be reproduced and explained than to make it disappear quickly.

==================================================
4. Q&A
==================================================

Q1. {keyword}를 처음 사용할 때 가장 먼저 확인해야 할 것은 무엇인가요?

핵심 요약은 원본을 보호하고 적용 범위를 확인하는 것입니다. 해결 방법은 파일 탐색기에서 원본 파일을 복사한 뒤 복사본에서 작업을 시작하는 것입니다. 예를 들어 문서라면 파일 탐색기 → 대상 파일 마우스 오른쪽 클릭 → 복사 → 붙여넣기 → 복사본 열기 순서로 준비합니다. 그다음 상단 메뉴 → 관련 탭 → 설정 또는 옵션 버튼을 클릭해 열리는 창에서 적용 범위를 확인합니다. 주의할 점은 전체 문서와 선택 영역을 혼동하면 의도하지 않은 부분까지 바뀔 수 있다는 것입니다. 실전 팁은 확인 버튼을 누르기 전 창 이름과 선택된 옵션을 짧게 메모해 두는 것입니다.

Q1. What should I check first when using {keyword} for the first time?

The key point is to protect the original file and check the target range. The solution is to copy the original file in File Explorer and start working in the copied file. For example, for a document, use File Explorer → right-click the target file → Copy → Paste → open the copied file. Then go to the top menu, choose the related tab, and click Settings or Options to check the range in the window that opens. Be careful because confusing the whole document with the selected area can change parts you did not intend to modify. A practical tip is to briefly note the window name and selected options before clicking OK.

Q2. {keyword}는 언제 사용하는 것이 가장 효과적인가요?

핵심 요약은 새 작업을 시작하기 전, 반복 작업을 표준화할 때, 오류를 점검할 때 효과적이라는 것입니다. 해결 방법은 작업 목적을 먼저 정하고, 그 목적에 맞는 메뉴와 옵션만 선택하는 것입니다. 예를 들어 보고서를 매달 만든다면 상단 메뉴 → 파일 → 다른 이름으로 저장에서 템플릿을 만든 뒤, 관련 탭의 설정 창에서 자주 쓰는 옵션을 저장합니다. 주의할 점은 모든 상황에 같은 설정을 적용하면 오히려 결과가 어긋날 수 있다는 것입니다. 실전 팁은 업무 유형별로 “신규 작성용”, “수정용”, “오류 점검용”처럼 절차를 나누어 기록하는 것입니다.

Q2. When is {keyword} most effective?

The key point is that it is most effective before starting a new task, when standardizing repeated work, and when checking errors. The solution is to define the purpose first and select only the menu and options that match that purpose. For example, if you create a report every month, use the top menu → File → Save As to create a template, and then save frequently used options in the settings window of the related tab. Be careful because applying the same setting to every situation can produce incorrect results. A practical tip is to record separate procedures such as “for new work,” “for editing,” and “for error checking.”

Q3. 메뉴 위치나 버튼 이름이 화면에서 다르게 보이면 어떻게 해야 하나요?

핵심 요약은 화면 버전이 달라도 작업 흐름을 기준으로 찾으면 된다는 것입니다. 해결 방법은 상단 메뉴, 왼쪽 사이드바, 오른쪽 속성 패널, 설정 창 순서로 관련 기능을 찾는 것입니다. 예를 들어 버튼 이름이 옵션이 아니라 환경 설정으로 보일 수 있고, 설정 창이 대화상자 또는 속성 패널 형태로 열릴 수도 있습니다. 이때는 창 안에서 적용 범위, 미리보기, 확인, 취소 같은 공통 항목을 확인하면 됩니다. 주의할 점은 비슷한 이름의 버튼을 바로 누르지 말고 설명 문구나 선택된 범위를 먼저 읽어야 한다는 것입니다. 실전 팁은 한 번 찾은 메뉴 경로를 문서 맨 아래에 기록해 두면 다음 작업에서 시간을 줄일 수 있다는 것입니다.

Q3. What should I do if the menu location or button name looks different on my screen?

The key point is to search by workflow even when the screen version is different. The solution is to check the top menu, left sidebar, right property panel, and settings window in that order. For example, a button may be named Preferences instead of Options, and a settings window may open as a dialog box or a property panel. In that case, look for common items such as target range, preview, OK, and Cancel inside the window. Be careful not to click a similar-looking button immediately; read the description and selected range first. A practical tip is to record the menu path at the bottom of your work note after finding it once.

Q4. 적용 후 결과가 이상하면 바로 저장해도 되나요?

핵심 요약은 결과가 이상할 때는 바로 저장하지 말아야 한다는 것입니다. 해결 방법은 먼저 Ctrl+Z로 되돌릴 수 있는지 확인하고, 되돌리기가 가능하면 원래 상태로 복구한 뒤 적용 범위를 다시 선택하는 것입니다. 예를 들어 설정 창에서 전체 문서를 선택했는데 일부 영역만 바꾸고 싶었다면, 취소하거나 되돌린 뒤 필요한 영역을 드래그로 선택하고 다시 상단 메뉴 → 관련 탭 → 설정 버튼 순서로 들어갑니다. 주의할 점은 자동 저장이 켜져 있으면 실수가 빠르게 저장될 수 있다는 것입니다. 실전 팁은 큰 변경 전에는 파일 이름 뒤에 `_backup` 또는 날짜를 붙인 복사본을 만들어 두는 것입니다.

Q4. Should I save immediately if the result looks wrong after applying it?

The key point is that you should not save immediately when the result looks wrong. The solution is to check whether Ctrl+Z can restore the previous state, and if it can, go back and select the target range again. For example, if you selected the whole document in the settings window but wanted to change only one section, cancel or undo the change, drag the needed area, and then go back through the top menu → related tab → Settings button. Be careful because autosave can save mistakes quickly. A practical tip is to create a copy with `_backup` or the date in the file name before making a large change.

Q5. 팀에서 {keyword}를 함께 사용할 때는 무엇을 정해 두어야 하나요?

핵심 요약은 메뉴 경로, 적용 범위, 저장 기준을 팀 기준으로 정해야 한다는 것입니다. 해결 방법은 작업 절차를 한 문서에 정리하고, 각 단계마다 어떤 창이 열리는지와 어떤 옵션을 선택하는지 적는 것입니다. 예를 들어 “상단 메뉴 → 관련 탭 → 설정 창 → 적용 범위 선택 → 확인”처럼 클릭 순서를 고정하면 담당자가 바뀌어도 결과가 흔들리지 않습니다. 주의할 점은 개인 컴퓨터에서만 보이는 경로나 개인 계정 설정을 팀 표준으로 삼으면 안 된다는 것입니다. 실전 팁은 템플릿 파일과 절차 문서를 같은 폴더에 두고, 수정 날짜와 담당자를 함께 기록하는 것입니다.

Q5. What should a team define when using {keyword} together?

The key point is that the team should define the menu path, target range, and saving standard. The solution is to write the work procedure in one document and describe which window opens and which option should be selected at each step. For example, fixing the click order as “top menu → related tab → settings window → choose target range → OK” keeps the result consistent even when the person in charge changes. Be careful not to use a path visible only on one personal computer or a personal account setting as the team standard. A practical tip is to keep the template file and procedure document in the same folder and record the revision date and person in charge.

==================================================
5. 결론
==================================================

{keyword}를 잘 사용하는 핵심은 기능 이름을 외우는 것이 아니라, 실제 작업 흐름 안에서 언제 필요한지 판단하는 것입니다. 먼저 원본을 보호하고, 적용 범위를 정하고, 상단 메뉴에서 관련 탭을 찾고, 설정 창에서 옵션을 선택한 뒤, 결과를 검토하는 순서를 지키면 대부분의 실수를 줄일 수 있습니다. 특히 업무 문서나 반복 작업에서는 개인의 기억보다 절차가 더 중요합니다. 절차가 있으면 같은 작업을 다시 할 때 시간이 줄고, 다른 사람에게 넘겨도 결과가 일정하게 유지됩니다. 따라서 {keyword}는 단순한 기능이 아니라 업무 품질을 안정적으로 만드는 실무 도구로 보는 것이 좋습니다.

The key to using {keyword} well is not memorizing the feature name, but knowing when it is needed inside the actual workflow. If you protect the original file, define the target range, find the related tab in the top menu, choose options in the settings window, and review the result, most mistakes can be reduced. In work documents and repeated tasks, a procedure is more important than personal memory. With a procedure, the same task takes less time later and the result stays consistent even when another person takes over. Therefore, {keyword} should be treated not as a simple function, but as a practical tool that stabilizes work quality.

마지막으로, 좋은 글과 좋은 작업 절차는 같은 원리를 가집니다. 필요한 이유를 먼저 설명하고, 실제로 어떻게 하는지 단계별로 보여 주며, 어떤 상황에서 써야 하는지 판단 기준을 제공합니다. 이 글의 방식처럼 한글과 영문을 문단 단위로 함께 정리하면 국내 독자와 영어 자료를 참고하는 독자 모두에게 도움이 됩니다. 예제는 실제 업무 상황을 기준으로 세 개만 깊게 다루고, Q&A는 자주 생기는 질문 다섯 개를 충분히 설명하는 것이 가장 안정적입니다. 이런 구조를 유지하면 {keyword}와 관련된 글은 정보 나열이 아니라 바로 따라 할 수 있는 실무 콘텐츠가 됩니다.

Finally, a good article and a good work procedure follow the same principle. They explain why something is needed first, show how to do it step by step, and provide criteria for deciding when to use it. When Korean and English are organized in parallel by paragraph, as in this article, the content becomes useful both for Korean readers and for readers who refer to English materials. It is most stable to cover exactly three examples deeply based on real work situations and explain exactly five Q&A items with enough detail. If this structure is maintained, an article about {keyword} becomes practical content that readers can follow, not just a list of information.
""".strip()

    if len(article) < 5000:
        raise ValueError("Generated article is shorter than 5,000 characters.")

    return article


def main():
    print("[refine_drafts_ai.py] 실행 시작")
    print("규칙 고정형 완성 글 txt 저장 시작")

    if not TOP10_PATH.exists():
        print("topic_top10.csv 파일이 없습니다.")
        print(f"확인 위치: {TOP10_PATH}")
        return

    top10_df = pd.read_csv(TOP10_PATH, encoding="utf-8-sig")

    if top10_df.empty:
        print("topic_top10.csv가 비어 있습니다.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    date_dir = OUTPUT_DIR / today
    date_dir.mkdir(parents=True, exist_ok=True)

    saved_count = 0

    for index, row in top10_df.iterrows():
        platform = clean_value(row.get("platform", "platform"), "platform")
        title = clean_value(row.get("title", ""), clean_value(row.get("keyword", ""), "제목 없음"))

        article_text = create_ai_article(row)

        safe_platform = make_safe_filename(platform)
        safe_title = make_safe_filename(title)

        file_number = str(index + 1).zfill(2)
        final_path = date_dir / f"{file_number}_{safe_platform}_{safe_title}.txt"

        final_path.write_text(article_text, encoding="utf-8")

        saved_count += 1
        print(f"저장 완료: {final_path}")

    print("규칙 고정형 완성 글 txt 저장 완료")
    print(f"저장 개수: {saved_count}")
    print(f"저장 위치: {date_dir}")


if __name__ == "__main__":
    main()
