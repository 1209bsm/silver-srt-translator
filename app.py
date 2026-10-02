import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
import streamlit as st

# Python 3.13+ 환경에서 삭제된 cgi 모듈 호환성 패치 (기타 모듈 충돌 방지)
if "cgi" not in sys.modules:
    import types

    cgi_mock = types.ModuleType("cgi")


    def parse_header(line):
        if not line:
            return "", {}
        parts = line.split(";")
        key = parts[0].strip()
        pdict = {}
        for p in parts[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                pdict[k.strip().lower()] = v.strip().strip('"\'')
        return key, pdict


    cgi_mock.parse_header = parse_header
    sys.modules["cgi"] = cgi_mock


# 외부 라이브러리 설치 없이 파이썬 기본 내장 모듈(urllib)을 활용하는 번역기 클래스
class SimpleTranslator:
    def translate(self, text, src="auto", dest="ko"):
        if not text.strip():
            class Dummy:
                text = ""

            return Dummy()

        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": src,
            "tl": dest,
            "dt": "t",
            "q": text,
        }
        encoded_params = urllib.parse.urlencode(params)
        full_url = f"{url}?{encoded_params}"

        # 일반 브라우저처럼 보이도록 User-Agent 강화
        req = urllib.request.Request(
            full_url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            translated_text = "".join(
                [sentence[0] for sentence in result[0] if sentence[0]]
            )

            class TranslatedResult:
                text = translated_text

            return TranslatedResult()


# 페이지 설정
st.set_page_config(
    page_title="양방향 자막 번역기", page_icon="🌐", layout="centered"
)

st.title("🌐 자막 파일 양방향 번역 서비스")
st.write(
    "자막 파일(`.srt` 또는 `.txt`)을 업로드하여 **한글 ➡️ 다국어** 또는 **외국어"
    " ➡️ 한글**로 자유롭게 번역할 수 있습니다."
)

# 세션 상태 초기화 (다운로드 시 화면 초기화 방지용)
if "translated_data" not in st.session_state:
    st.session_state.translated_data = None
if "last_file_name" not in st.session_state:
    st.session_state.last_file_name = None
if "last_mode" not in st.session_state:
    st.session_state.last_mode = None

# 번역 모드 선택
mode = st.radio(
    "번역 방향을 선택하세요:",
    [
        "한글 자막 ➡️ 다국어 번역 (영어, 중국어, 일본어, 인도네시아어)",
        "외국어 자막 ➡️ 한글 번역",
    ],
    horizontal=False,
)

# 지원할 타겟 언어 설정 (한글 -> 다국어 모드용)
LANGUAGES = {
    "영어 (English)": {"code": "en", "suffix": "_EN.srt"},
    "중국어 간체 (Chinese Simplified)": {"code": "zh-cn", "suffix": "_ZH-CN.srt"},
    "중국어 번체 (Chinese Traditional)": {"code": "zh-tw", "suffix": "_ZH-TW.srt"},
    "일본어 (Japanese)": {"code": "ja", "suffix": "_JA.srt"},
    "인도네시아어 (Indonesian)": {"code": "id", "suffix": "_ID.srt"},
}


def parse_srt(content):
    """SRT 파일을 파싱하여 (번호, 타임스탬프, 텍스트) 리스트로 반환합니다."""
    # 운영체제별 줄바꿈 문자(\r\n, \r)를 유닉스 스타일(\n)로 강제 통일하여 정규식 오류 방지
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    
    # 타임스탬프 앞뒤 공백이나 여러 줄의 빈 줄을 유연하게 처리하는 정규식
    pattern = re.compile(
        r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n{2,}|\Z)",
        re.DOTALL,
    )
    matches = pattern.findall(content)
    subtitles = []
    for match in matches:
        index, timestamp, text = match
        subtitles.append({"index": index, "timestamp": timestamp, "text": text.strip()})
    return subtitles


def generate_srt(subtitles):
    """파싱된 자막 데이터를 다시 SRT 형식의 문자열로 변환합니다."""
    output = []
    for sub in subtitles:
        output.append(f"{sub['index']}\n{sub['timestamp']}\n{sub['text']}\n")
    return "\n".join(output)


# 파일 업로드 위젯
uploaded_file = st.file_uploader(
    "자막 파일(`.srt` 또는 `.txt`)을 업로드하세요", type=["srt", "txt"]
)

# 파일이 바뀌거나 모드가 바뀌면 기존 번역 결과 세션 초기화
if uploaded_file is not None:
    if st.session_state.last_file_name != uploaded_file.name or st.session_state.last_mode != mode:
        st.session_state.translated_data = None
        st.session_state.last_file_name = uploaded_file.name
        st.session_state.last_mode = mode

if uploaded_file is not None:
    try:
        # 파일 읽기 (UTF-8 우선, 실패 시 CP949 인코딩 시도)
        file_bytes = uploaded_file.read()
        try:
            file_content = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            file_content = file_bytes.decode("cp949")

        subtitles = parse_srt(file_content)

        if not subtitles:
            st.error(
                "자막 형식을 인식할 수 없습니다. 올바른 `.srt` 또는 자막 형식의 `.txt`"
                " 파일인지 확인해주세요."
            )
        else:
            st.success(
                f"총 {len(subtitles)}개의 자막 라인을 성공적으로 읽어왔습니다!"
            )

            base_filename = os.path.splitext(uploaded_file.name)[0]
            translator = SimpleTranslator()

            # -------------------------------------------------------------
            # [모드 1] 한글 자막 ➡️ 다국어 번역
            # -------------------------------------------------------------
            if mode == "한글 자막 ➡️ 다국어 번역 (영어, 중국어, 일본어, 인도네시아어)":
                if st.button("🚀 다국어 자막으로 번역 시작하기"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    translated_results = {}
                    total_langs = len(LANGUAGES) + 1  # 한국어 원본 포함

                    # 1. 한국어 원본/정리본 SRT 결과 추가
                    ko_srt_result = generate_srt(subtitles)
                    translated_results["한국어 (Korean)"] = {
                        "filename": f"{base_filename}_KO.srt",
                        "data": ko_srt_result,
                    }

                    error_occurred = False
                    error_message = ""

                    for i, (lang_name, info) in enumerate(LANGUAGES.items()):
                        status_text.text(f"{lang_name} 번역 중...")

                        translated_subtitles = []
                        for sub in subtitles:
                            text = sub["text"].replace("\n", " ")
                            if not text.strip():
                                translated_subtitles.append({
                                    "index": sub["index"],
                                    "timestamp": sub["timestamp"],
                                    "text": "",
                                })
                                continue

                            translated_text = text
                            for attempt in range(3):
                                try:
                                    translated = translator.translate(
                                        text, src="ko", dest=info["code"]
                                    )
                                    if translated and translated.text:
                                        translated_text = translated.text
                                        break
                                except Exception as e:
                                    if attempt == 2:
                                        error_occurred = True
                                        error_message = str(e)
                                        # 치명적 오류 방지: 번역 실패 시 멈추지 않고 원본 텍스트를 대입하여 계속 진행
                                        translated_text = f"[번역오류] {text}"
                                    else:
                                        # API 차단 방지를 위한 백오프 대기 (실패 시 대기 시간 증가)
                                        time.sleep(1.0 + attempt)

                            translated_subtitles.append({
                                "index": sub["index"],
                                "timestamp": sub["timestamp"],
                                "text": translated_text,
                            })
                            # 너무 빠른 요청으로 인한 IP 차단 방지 딜레이
                            time.sleep(0.15)

                        srt_result = generate_srt(translated_subtitles)
                        filename = f"{base_filename}{info['suffix']}"
                        translated_results[lang_name] = {
                            "filename": filename,
                            "data": srt_result,
                        }

                        progress_bar.progress((i + 1) / total_langs)

                    status_text.text("모든 번역이 완료되었습니다!")
                    if error_occurred:
                        st.warning(
                            f"⚠ 일부 문장 번역 중 API 통신 지연이 있었습니다. 파일은 정상적으로 생성되었습니다. (참고 에러: {error_message})"
                        )
                    else:
                        st.balloons()
                    
                    # 결과를 세션에 저장
                    st.session_state.translated_data = translated_results

            # -------------------------------------------------------------
            # [모드 2] 외국어 자막 ➡️ 한글 번역
            # -------------------------------------------------------------
            else:
                if st.button("🚀 한글 자막으로 번역 시작하기"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    status_text.text("한글로 번역 중...")
                    translated_subtitles = []
                    total_subs = len(subtitles)
                    error_occurred = False
                    error_message = ""

                    for idx, sub in enumerate(subtitles):
                        text = sub["text"].replace("\n", " ")
                        if not text.strip():
                            translated_subtitles.append({
                                "index": sub["index"],
                                "timestamp": sub["timestamp"],
                                "text": "",
                            })
                            continue

                        translated_text = text
                        for attempt in range(3):
                            try:
                                translated = translator.translate(
                                    text, src="auto", dest="ko"
                                )
                                if translated and translated.text:
                                    translated_text = translated.text
                                    break
                            except Exception as e:
                                if attempt == 2:
                                    error_occurred = True
                                    error_message = str(e)
                                    # 치명적 오류 방지: 번역 실패 시 멈추지 않고 원문 유지
                                    translated_text = f"[번역오류] {text}"
                                else:
                                    time.sleep(1.0 + attempt)

                        translated_subtitles.append({
                            "index": sub["index"],
                            "timestamp": sub["timestamp"],
                            "text": translated_text,
                        })
                        progress_bar.progress((idx + 1) / total_subs)
                        time.sleep(0.15)

                    srt_result = generate_srt(translated_subtitles)
                    output_filename = f"{base_filename}_KO.srt"

                    status_text.text("한글 번역이 완료되었습니다!")
                    if error_occurred:
                        st.warning(
                            f"⚠ 일부 문장 번역 중 API 통신 지연이 있었습니다. 파일은 정상적으로 생성되었습니다. (참고 에러: {error_message})"
                        )
                    else:
                        st.balloons()

                    # 결과를 세션에 딕셔너리 형태로 저장
                    st.session_state.translated_data = {
                        "한글 번역본": {
                            "filename": output_filename,
                            "data": srt_result
                        }
                    }

            # =============================================================
            # 세션에 저장된 번역 결과가 있다면 다운로드 UI 렌더링
            # (버튼 클릭 후 재실행되어도 화면이 유지됨)
            # =============================================================
            if st.session_state.translated_data:
                st.markdown("---")
                st.subheader("📥 번역된 자막 파일 다운로드")

                data_dict = st.session_state.translated_data

                # 다국어 번역 (결과물이 여러 개인 경우 ZIP 다운로드 제공)
                if mode == "한글 자막 ➡️ 다국어 번역 (영어, 중국어, 일본어, 인도네시아어)" and len(data_dict) > 1:
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(
                        zip_buffer, "w", zipfile.ZIP_DEFLATED
                    ) as zip_file:
                        for lang_name, res in data_dict.items():
                            zip_file.writestr(res["filename"], res["data"])
                    zip_buffer.seek(0)

                    st.download_button(
                        label="📦 모든 번역 파일 한번에 다운로드 (ZIP)",
                        data=zip_buffer,
                        file_name=f"{base_filename}_translated_subtitles.zip",
                        mime="application/zip",
                    )
                    st.markdown("---")

                # 개별 다운로드 버튼
                for lang_name, res in data_dict.items():
                    st.download_button(
                        label=f"⬇️️ {lang_name} 다운로드 ({res['filename']})",
                        data=res["data"],
                        file_name=res["filename"],
                        mime="text/plain",
                    )

    except Exception as e:
        st.error(f"파일을 처리하는 동안 예기치 못한 오류가 발생했습니다: {e}")

# 화면 하단 푸터 (번역 엔진 안내)
st.markdown("---")
st.caption("💡 본 서비스는 파이썬 내장 모듈을 활용한 자체 API 통신으로 안정적으로 동작합니다.")
