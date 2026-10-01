import io
import os
import re
import time
import zipfile
import streamlit as st
from deep_translator import MicrosoftTranslator

# 페이지 설정
st.set_page_config(
    page_title="자막 다국어 번역기", page_icon="🌐", layout="centered"
)

st.title("🌐 자막 파일 다국어 번역 서비스")
st.write(
    "한글 자막 파일(`.srt`)을 업로드하면 중국어(간체/번체), 일본어, 인도네시아어,"
    " 영어 자막 파일로 각각 변환하여 다운로드할 수 있습니다."
)

# 지원할 타겟 언어 설정 (Microsoft Translator 기준 언어 코드 적용)
LANGUAGES = {
    "영어 (English)": {"code": "en", "suffix": "_EN.srt"},
    "중국어 간체 (Chinese Simplified)": {
        "code": "zh-Hans",
        "suffix": "_ZH-CN.srt",
    },
    "중국어 번체 (Chinese Traditional)": {
        "code": "zh-Hant",
        "suffix": "_ZH-TW.srt",
    },
    "일본어 (Japanese)": {"code": "ja", "suffix": "_JA.srt"},
    "인도네시아어 (Indonesian)": {"code": "id", "suffix": "_ID.srt"},
}


def parse_srt(content):
  """SRT 파일을 파싱하여 (번호, 타임스탬프, 텍스트) 리스트로 반환합니다."""
  pattern = re.compile(
      r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\Z)",
      re.DOTALL,
  )
  matches = pattern.findall(content)
  subtitles = []
  for match in matches:
    index, timestamp, text = match
    subtitles.append({"index": index, "timestamp": timestamp, "text": text})
  return subtitles


def generate_srt(subtitles):
  """파싱된 자막 데이터를 다시 SRT 형식의 문자열로 변환합니다."""
  output = []
  for sub in subtitles:
    output.append(f"{sub['index']}\n{sub['timestamp']}\n{sub['text']}\n")
  return "\n".join(output)


def translate_subtitles_safe(subtitles, target_code):
  """MicrosoftTranslator를 사용하여 클라우드 차단 없이 안전하게 한 줄씩 번역합니다."""
  translated_texts = []
  for sub in subtitles:
    text = sub["text"].replace("\n", " ")
    if not text.strip():
      translated_texts.append("")
      continue

    try:
      translated = MicrosoftTranslator(source="ko", target=target_code).translate(
          text
      )
      if translated:
        translated_texts.append(translated)
      else:
        translated_texts.append(text)
    except Exception:
      translated_texts.append(text)

    # 서버 부하 방지 및 안정적인 번역을 위한 미세 딜레이
    time.sleep(0.1)

  return translated_texts


# 파일 업로드 위젯
uploaded_file = st.file_uploader(
    "한글 자막 파일(.srt)을 업로드하세요", type=["srt"]
)

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
          "자막 형식을 인식할 수 없습니다. 올바른 `.srt` 파일인지 확인해주세요."
      )
    else:
      st.success(
          f"총 {len(subtitles)}개의 자막 라인을 성공적으로 읽어왔습니다!"
      )

      if st.button("🚀 자막 번역 시작하기"):
        progress_bar = st.progress(0)
        status_text = st.empty()

        base_filename = os.path.splitext(uploaded_file.name)[0]
        translated_results = {}

        total_langs = len(LANGUAGES)
        for i, (lang_name, info) in enumerate(LANGUAGES.items()):
          status_text.text(f"{lang_name} 번역 중...")

          # 안정적인 번역 함수 호출
          translated_texts = translate_subtitles_safe(
              subtitles, info["code"]
          )

          translated_subtitles = []
          for idx, sub in enumerate(subtitles):
            translated_subtitles.append({
                "index": sub["index"],
                "timestamp": sub["timestamp"],
                "text": translated_texts[idx]
                if idx < len(translated_texts)
                else sub["text"],
            })

          srt_result = generate_srt(translated_subtitles)
          filename = f"{base_filename}{info['suffix']}"
          translated_results[lang_name] = {
              "filename": filename,
              "data": srt_result,
          }

          progress_bar.progress((i + 1) / total_langs)

        status_text.text("모든 번역이 완료되었습니다!")
        st.balloons()

        st.markdown("---")
        st.subheader("📥 번역된 자막 파일 다운로드")

        # 1. 전체 파일 한 번에 다운로드 (ZIP) 버튼
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(
            zip_buffer, "w", zipfile.ZIP_DEFLATED
        ) as zip_file:
          for lang_name, res in translated_results.items():
            zip_file.writestr(res["filename"], res["data"])
        zip_buffer.seek(0)

        st.download_button(
            label="📦 모든 번역 파일 한번에 다운로드 (ZIP)",
            data=zip_buffer,
            file_name=f"{base_filename}_translated_subtitles.zip",
            mime="application/zip",
        )

        st.markdown("---")

        # 2. 언어별 개별 다운로드 버튼
        for lang_name, res in translated_results.items():
          st.download_button(
              label=f"⬇️ {lang_name} 자막 다운로드 ({res['filename']})",
              data=res["data"],
              file_name=res["filename"],
              mime="text/plain",
          )

  except Exception as e:
    st.error(f"파일을 처리하는 동안 오류가 발생했습니다: {e}")
