# 貢獻指南

感謝你協助改善 AI 英文口試練習系統。提交變更前，請先確認內容不含真實
學生資料、學號、錄音、照片、資料庫備份、API 金鑰或部署環境檔。

## 開發流程

1. 從 `main` 建立短期分支。
2. 複製範例設定：`cp .env.example .env`，只在本機填入測試用值。
3. 安裝 Python 3.11 與 `requirements-dev.txt` 的開發／測試依賴。
4. 完成小而聚焦的變更，並為行為變更新增或更新測試。
5. 執行驗證：

   ```bash
   PYTHONPYCACHEPREFIX=/tmp/meet-pycache PYTHONPATH=. pytest -q
   node --test tests/js/*.test.mjs
   git diff --check
   ```

6. 提交 Pull Request，說明問題、解法、驗證結果與任何資料庫／設定相容性影響。

## 貢獻授權

除非你在提交時明確以書面標示為「Not a Contribution」，否則你有意提交給
本專案收錄的貢獻，將依 [Apache License 2.0](LICENSE) 第 5 節提供，且不附加
額外條款。請只提交你有權授權的程式碼、文件、提示詞、題目、圖片及其他素材。

不要直接複製來源不明的網路內容。若變更包含第三方內容，請在 Pull Request
列出來源與授權，並同步更新 `THIRD_PARTY_NOTICES.md`。

## 程式與介面原則

- 後端 API 是權限邊界；不可把前端隱藏按鈕當成授權。
- 學生、課程管理員與受保護管理員的資料範圍必須有對應測試。
- 保留繁體中文介面原意，並區分 AI 練習回饋與教師正式評分。
- 上傳、匯入、匯出、AI 與郵件路徑應驗證大小、擁有者與失敗狀態。
- 不得在 log、錯誤訊息、測試 fixture 或截圖中放入真實個資或憑證。

## 回報安全問題

請不要用公開 Issue 揭露可利用的弱點或真實資料。請依
[`SECURITY.md`](SECURITY.md) 的私人通報流程處理。
