# 엠클래스수학과학전문학원

수학 문제집 PDF를 올리면 문제를 한 장씩 잘라, 풀이 공간이 있는 **검은 칠판 슬라이드**로 만들어 주는 수업용 도구입니다. 인터넷 없이 내 컴퓨터에서 브라우저로 실행됩니다.

## 설치와 실행 (Windows)

1. [Git](https://git-scm.com/download/win)과 [Python 3.12](https://www.python.org/downloads/release/python-3129/)를 설치합니다. (Python은 설치할 때 **Add python.exe to PATH** 체크)
2. 내려받기:
   ```bash
   git clone https://github.com/mclass-jjangdm/math_slide.git
   ```
3. 내려받은 `math_slide` 폴더의 **`start.bat`을 더블클릭**합니다. 처음 한 번은 필요한 라이브러리를 자동으로 설치하고(`.venv` 폴더), 이후에는 바로 실행됩니다. 브라우저가 자동으로 열립니다(http://localhost:8765).

### 바탕화면·시작 메뉴 바로가기 만들기
자주 쓴다면 **`make_shortcut.bat`을 더블클릭**하세요. 바탕화면과 시작 메뉴에 **"엠클래스수학과학전문학원"** 바로가기(아이콘 포함)가 만들어집니다.
작업표시줄에 고정하려면 바탕화면의 바로가기를 **마우스 오른쪽 버튼 → 작업 표시줄에 고정**(Windows 11은 "더 많은 옵션 표시" 안에 있을 수 있음)을 누르세요.
바로가기로 실행하면 검은 창이 **최소화된 채** 작업표시줄에 남습니다. 프로그램을 끝내려면 그 창을 닫으세요.
폴더를 옮기면 `make_shortcut.bat`을 다시 실행하세요.

### 앱 창으로 열기
Windows에 Edge나 Chrome이 있으면 프로그램이 **주소창·탭 없는 앱 창**으로 열립니다(설치형 프로그램처럼 보입니다). 일반 브라우저 탭으로 열고 싶으면 `start.bat --tab`으로 실행하세요.
프로그램을 끝내려면 첫 화면 오른쪽 위의 **⏻ 종료**를 누르면 됩니다(서버도 함께 꺼집니다).

직접 실행하려면:

```bash
pip install -r requirements.txt
python mathslide/server.py
```

업데이트: `math_slide` 폴더에서 `git pull`.

### 문제가 생기면
- `ImportError: DLL load failed while importing _extra` → 파이썬이 3.14 이상(미리보기 버전)이거나 Visual C++ 재배포 패키지가 없는 경우입니다. **Python 3.12를 설치**하고 `start.bat`을 다시 실행하세요. 그래도 안 되면 [VC++ 재배포 패키지](https://aka.ms/vs/17/release/vc_redist.x64.exe)를 설치하세요.
- 이미 `.venv` 폴더가 만들어졌는데 계속 오류가 나면 `.venv` 폴더를 지우고 다시 실행하세요.

## 기능

- **문제 자동 검출**: 큰 번호 글자(658), 글머리(`추가 1.` `문제 3)`), 스캔본(이미지 분석 + 숫자 인식)
- **검수 화면**: 상자 드래그·크기 조절, 체크로 문제 선택, 순서 바꾸기, 소문항 (1)(2)… 나누기, 번호 이어 매기기
- **수업 모드**: 검은 배경, 펜/형광펜/지우개, 필기 자동 저장, 문제 이동·크기 조절(두 손가락), 확대, 타이머, 문제 목록
- **정답 가리기**: 문제 안에 인쇄된 `(정답 : …)`을 가렸다가 버튼으로 보이기
- **내보내기**: 필기 포함 슬라이드 PDF, 학생용 유인물 PDF
- **화면 녹화**: 수업 모드 도구줄의 ⏺ 녹화 버튼으로 화면과 마이크 목소리를 함께 녹화해 `.webm` 파일로 저장 (다시 누르면 중지·저장)

## 구조

| 파일 | 역할 |
|---|---|
| `mathslide/server.py` | 로컬 서버(업로드, 이미지 잘라내기, PDF 내보내기) |
| `mathslide/detect.py` | 텍스트 PDF의 문제 영역 검출, 소문항 나누기, 정답 글자 찾기 |
| `mathslide/detect_scan.py` | 스캔본 문제 검출 |
| `mathslide/digits.py` | 번호 숫자 인식(템플릿 매칭) |
| `mathslide/static/index.html` | 화면(홈·검수·수업 모드) |
| `testdata/` | 시험 스크립트 |

업로드한 PDF와 필기 기록은 `mathslide/projects/`에 저장되며 저장소에는 올라가지 않습니다.
