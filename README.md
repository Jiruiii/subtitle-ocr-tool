# subtitle-ocr-tool

把影片畫面中的「燒錄字幕」辨識成可使用的逐字稿：

- transcript.srt：保留時間戳，可匯入播放器或剪輯軟體
- transcript.txt：連續重複字幕合併後的純文字稿
- wav/：每段字幕對應的 16 kHz、單聲道 WAV

這個工具只辨識畫面文字，不會辨識聲音。沒有燒錄字幕的影片請使用 ASR，例如 Whisper。

## 安裝

需要 Python 3.10 以上與 ffmpeg。安裝腳本會自動建立 `.venv`，偵測是否有
NVIDIA GPU，並安裝對應的 PaddlePaddle、PaddleOCR、OpenCV 與 yt-dlp。

先下載專案並執行安裝腳本：

~~~bash
git clone https://github.com/Jiruiii/subtitle-ocr-tool.git
cd subtitle-ocr-tool
python install.py
~~~

沒有 NVIDIA GPU 時，腳本會安裝 CPU 版；偵測到 NVIDIA GPU 時，會依
`nvidia-smi` 顯示的 CUDA 版本選擇官方可用的 GPU 套件。需要手動指定時：

~~~bash
python install.py --cpu
python install.py --gpu
python install.py --gpu --cuda 11.8
~~~

如果不想建立 `.venv`，才使用 `--no-venv`：

~~~bash
python install.py --no-venv
~~~

安裝腳本仍然使用 PaddlePaddle 官方套件來源；一般使用者不需要自行開啟
中國網站或手動下載 wheel。若自動安裝失敗，再參考[官方安裝文件](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/linux-pip_en.html)
選擇適合自己環境的版本。

安裝完成後，啟用虛擬環境：

~~~bash
# Linux/macOS
source .venv/bin/activate
~~~

~~~powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
~~~

## 最快用法

處理本地影片：

~~~bash
subtitle-ocr ./video.mp4 --output-dir outputs/video
~~~

處理 YouTube 影片：

~~~bash
subtitle-ocr \
  "https://www.youtube.com/watch?v=影片ID" \
  --output-dir outputs/影片ID
~~~

如果 YouTube 要求登入驗證，準備自己瀏覽器匯出的 Netscape cookies 檔案：

~~~bash
subtitle-ocr \
  "https://www.youtube.com/watch?v=影片ID" \
  --cookies ./youtube_cookies.txt \
  --output-dir outputs/影片ID
~~~

不要把 cookies 檔案提交到 Git。工具會在 URL 處理完成後刪除暫存下載檔；需要保留影片時加上 --keep-download。

第一次執行會下載 PaddleOCR 模型，之後會使用本機快取。

## 常用調整

字幕預設取影片底部 84% 到 99%。如果字幕被截掉，降低 --top；如果辨識到下方圖卡或其他文字，提高 --top：

~~~bash
subtitle-ocr ./video.mp4 \
  --top 0.68 \
  --bottom 0.99 \
  --interval 0.25 \
  --stability 2
~~~

常用參數：

| 參數 | 用途 | 預設 |
| --- | --- | --- |
| --device | cpu 或 gpu:0；省略時交給 PaddleOCR 自動選擇 | 自動 |
| --interval | 取樣間隔，秒數越小越精細但越慢 | 0.35 |
| --stability | 連續幾次相同才採用，降低短暫誤讀 | 3 |
| --top / --bottom | 字幕裁切區域比例 | 0.84 / 0.99 |
| --no-wav | 不呼叫 ffmpeg，只輸出 SRT/TXT | 關閉 |

## 批次處理

--url-file 每行放一個 YouTube URL 或本地影片路徑，# 開頭的行會忽略：

~~~text
https://www.youtube.com/watch?v=影片A
https://www.youtube.com/watch?v=影片B
./local-video.mp4
~~~

執行：

~~~bash
subtitle-ocr-batch \
  --url-file sources.txt \
  --output-root outputs \
  --workers 1
~~~

也可以直接傳多個來源：

~~~bash
subtitle-ocr-batch \
  "https://www.youtube.com/watch?v=影片A" \
  "https://www.youtube.com/watch?v=影片B"
~~~

處理播放清單時，工具預設不跳過任何影片：

~~~bash
subtitle-ocr-batch \
  "https://www.youtube.com/playlist?list=播放清單ID" \
  --skip-latest 2
~~~

已有完整輸出時會略過；要重新處理請加 --force。--workers 預設是 1，因為每個工作程序都會載入 OCR 模型；只有記憶體與 GPU 足夠時才提高。

## 只用既有 SRT 產生 WAV

不重新執行 OCR：

~~~bash
subtitle-ocr-wav ./video.mp4 \
  --srt ./old/transcript.srt \
  --txt ./old/transcript.txt \
  --output-dir ./outputs/video
~~~

來源也可以是 YouTube URL；需要登入時加上 --cookies。

## Python API

~~~python
from subtitle_ocr import PipelineConfig, run_pipeline

result = run_pipeline(
    "./video.mp4",
    "outputs/video",
    config=PipelineConfig(
        lang="chinese_cht",
        interval=0.35,
        top=0.84,
        bottom=0.99,
        stability=3,
    ),
)

print(result.srt_path)
print(len(result.events))
~~~

## 開發與測試

安裝開發依賴：

~~~bash
python -m pip install -e ".[dev]"
pytest
~~~

測試不會下載 PaddleOCR 模型或處理真實影片。

## 注意事項

- OCR 結果仍需人工校對，尤其是台語、專有名詞、標點與快速換字幕。
- 請只在有權限或符合平台使用條款的情況下載與處理影片。
- 請勿提交 youtube_cookies.txt、下載影片或 outputs/。
- 授權：Apache License 2.0。
