# AI 英文口試練習系統

幫助大學生練習英文面試的 AI 輔助平台。學生依序完成「欲應徵的職位 → 寫作練習 → 跟讀練習 → 角色扮演 → AI 回饋 → 心得撰寫」六個區段，老師（管理員）負責開放作業與正式批改。

本專案以 [Apache License 2.0](LICENSE) 開放原始碼。部署者需自行準備外部服務帳號，並負責學生資料告知、同意、保存、刪除及跨境傳輸等適用規範。本專案不附帶任何真實學生資料或可直接使用的服務憑證。

---

## 系統需求（部署前請確認）

| 項目 | 說明 |
|------|------|
| 伺服器 | OCI ARM VM（Ampere A1，Ubuntu 22.04 建議）|
| Docker | 需安裝 Docker 與 Docker Compose |
| OpenAI API | 提供 GPT 與 Whisper 功能 |
| Oracle Object Storage | 儲存學生錄音檔（S3 相容）|
| Cloudflare Turnstile | 登入防機器人驗證 |
| SMTP 信箱 | 發送通知信給學生 |

上述 OCI、Cloudflare、OpenAI 與外部 SMTP 是目前提供的部署範例，不是 Apache-2.0 授權的一部分，也不代表只能使用這些供應商。

---

## 本機開發與測試

建議使用 Python 3.11。請只把測試憑證放在未追蹤的 `.env`：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.development.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"
```

將最後一個指令輸出的亂數貼到 `.env` 的 `SECRET_KEY` 後再啟動；本機網址為 `http://localhost:7683`。

若要以 Docker 啟動本機服務：

```bash
docker compose up -d --build
```

執行測試：

```bash
PYTHONPYCACHEPREFIX=/tmp/meet-pycache PYTHONPATH=. pytest -q
node --test tests/js/*.test.mjs
```

請勿使用真實學生資料作為開發 fixture，也不要把 `.env`、database dump、匯出檔、錄音或照片提交到版本控制。

---

## 第一步：安裝 Docker（OCI ARM 伺服器）

> 如果你的伺服器已經裝好 Docker，可以跳過這一步。

```bash
# 更新套件
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# 加入 Docker 官方金鑰
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# 加入 Docker 軟體庫（ARM64）
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list

# 安裝 Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 讓目前使用者不需要 sudo 就能用 Docker
sudo usermod -aG docker $USER

# 重新登入後才會生效，先登出：
exit
```

重新 SSH 登入後，測試 Docker 是否正常：

```bash
docker run hello-world
```

看到 `Hello from Docker!` 就代表安裝成功。

---

## 第二步：下載專案

```bash
git clone <你的-repo-網址> /home/ubuntu/meet
cd /home/ubuntu/meet
```

---

## 第三步：設定 Oracle Object Storage

這是用來存放學生錄音的雲端空間（免費方案有 10 GB）。

1. 登入 **OCI Console** → Object Storage → **Create Bucket**
   - Bucket 名稱：自訂（例如 `meet-audio`）
   - Visibility：**Private**（私人，不對外公開）

2. 取得存取金鑰：
   - Identity → Users → 你的帳號 → **Customer Secret Keys** → **Generate Secret Key**
   - 複製 **Access Key ID** 和 **Secret Access Key**（Secret Key 只會顯示一次！）

3. 找到你的 Namespace：
   - Object Storage 頁面右上角可以看到 `Namespace: xxxxxxxxxx`

4. 組合 S3 端點網址格式：
   ```
   https://<namespace>.compat.objectstorage.<region>.oraclecloud.com
   ```
   例如：`https://axxxxxabc.compat.objectstorage.ap-tokyo-1.oraclecloud.com`

---

## 第四步：設定 Cloudflare Turnstile（登入防機器人）

1. 登入 **Cloudflare Dashboard** → Turnstile → **Add Site**
2. 填入你的網域（或 IP）
3. 複製 **Site Key** 和 **Secret Key**

---

## 第五步：設定 production 環境變數

```bash
cp .env.example .env.production
nano .env.production
```

依照以下說明逐一填寫，**不要留下範例的假值**：

```env
# ── 資料庫 ──────────────────────────────────────────────────
POSTGRES_USER=meet
POSTGRES_PASSWORD=請換成你自己的密碼          # 例如 MyStr0ngPwd!
POSTGRES_DB=meetdb
DATABASE_URL=postgresql://meet:請換成你自己的密碼@db:5432/meetdb
# 注意：DATABASE_URL 裡的密碼要和 POSTGRES_PASSWORD 一樣

# ── JWT 金鑰 ─────────────────────────────────────────────────
# 用以下指令產生一個安全的亂數金鑰：
# python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=貼上剛產生的金鑰
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_HOURS=8

# ── OpenAI ───────────────────────────────────────────────────
OPENAI_API_KEY=sk-...

# ── Oracle Object Storage ────────────────────────────────────
OCI_ENDPOINT_URL=https://<namespace>.compat.objectstorage.<region>.oraclecloud.com
OCI_ACCESS_KEY_ID=你的-access-key-id
OCI_SECRET_ACCESS_KEY=你的-secret-access-key
OCI_BUCKET_NAME=meet-audio          # 要和你建立的 Bucket 名稱一致
OCI_REGION=ap-tokyo-1               # 依你的 Bucket 所在區域填寫

# ── SMTP 寄件設定─────────────────────────────────────
MAIL_HOST=smtp.example.com
MAIL_PORT=587
MAIL_USER=你的-SMTP-使用者名稱
MAIL_PASSWORD=你的-SMTP-密碼
MAIL_FROM=已驗證的寄件信箱
MAIL_FROM_NAME=英文口試練習系統     # 寄件者顯示名稱
MAIL_REPLY_TO=回覆信箱
MAIL_STARTTLS=true
MAIL_SSL_TLS=false
MAIL_SIGNATURE_HTML=                # 可選：信件頁尾 HTML，留空也沒關係

# ── Cloudflare Turnstile ─────────────────────────────────────
TURNSTILE_SECRET_KEY=你的-turnstile-secret-key
TURNSTILE_SITE_KEY=你的-turnstile-site-key

# ── 應用程式 ─────────────────────────────────────────────────
APP_ENV=production
APP_ENV_FILE=.env.production
MEET_IMAGE=你的-registry/meet@sha256:填入本次建置映像的-digest
CORS_ORIGINS=https://你的網域.com   # 或 http://你的伺服器IP:7682
TUNNEL_TOKEN=你的-cloudflare-tunnel-token
```

> `MAIL_PASSWORD` 請填入 SMTP 服務商核發的密碼，不一定與帳號登入密碼相同。

---

## 第六步：啟動服務

```bash
cd /home/ubuntu/meet

# 會先啟動 db，再由 migrate service 執行 baseline、系統資料 bootstrap
# 與 alembic check；全部成功後 web 才會啟動。
docker compose --env-file .env.production -f docker-compose-production.yml up -d

# 確認 db / web 都在跑，migrate 應該已完成並退出
docker compose --env-file .env.production -f docker-compose-production.yml ps

# 看即時 log（Ctrl+C 離開）
docker compose --env-file .env.production -f docker-compose-production.yml logs -f web
```

服務啟動後，網站位於：`http://你的伺服器IP:7682`

---

## 第七步：確認資料庫初始化

production compose 會自動跑：

```bash
docker compose --env-file .env.production -f docker-compose-production.yml run --rm migrate
```

這個指令安全且可重複執行；它會執行 `scripts/bootstrap_database.py`，套用 migration、建立或修復唯一的系統評分規準與三個系統提示詞，最後以 `alembic check` 確認 ORM 沒有 drift。預設作業不會自動建立，須由管理員在作業頁明確同步。

目前 migration 是全新資料庫專用的 current-schema baseline，不支援從舊 revision 直接升級。部署此版本前必須依維護手冊備份並重建 PostgreSQL volume。

若要確認目前版本：

```bash
docker compose --env-file .env.production -f docker-compose-production.yml exec db \
  psql -U meet -d meetdb -c "select version_num from alembic_version;"
```

---

## 第八步：建立第一個管理員帳號

```bash
docker compose --env-file .env.production -f docker-compose-production.yml exec web python scripts/init_admin.py \
  --name "系統管理員" \
  --student-id admin001 \
  --email admin@example.com
```

指令會以不顯示輸入內容的方式要求輸入並再次確認密碼；密碼不會出現在 shell history 或 process list。成功後會顯示帳號資訊。

然後到 `http://你的伺服器IP:7682/login`，用 `admin001` 和剛設定的密碼登入。

> 之後新增其他管理員帳號，請登入後到 `/admin/users` 操作，**沒有公開的管理員註冊頁面**。

---

## 學生操作流程

每個作業包含六個區段，依序完成：

| 環節 | 內容 |
|------|------|
| 1. 欲應徵的職位 | 設定目標職位、工作內容與需要能力 |
| 2. 寫作練習 | 寫初稿 → 取得 AI 練習回饋 → 寫終稿 |
| 3. 跟讀練習 | 系統將終稿轉成語音，學生跟讀並錄音上傳 |
| 4. 角色扮演 | 回答 4 題核心題目與 1 題未預告的臨場追問 |
| 5. AI 回饋 | 整理整場面試的優勢與具體改進建議，不作為老師正式成績 |
| 6. 心得撰寫 | 對照作答與 AI 回饋完成反思，再由老師正式批改 |

系統預設有 5 份作業（個人背景、技能成就、情境應變、工作態度、公司認識），老師只需設定開放日期與截止日期。每份作業最多可提交 3 次。

---

## 常用指令

```bash
# 測試/本機環境：使用 .env 或指定 APP_ENV_FILE=.env.test
docker compose up -d --build

# production 環境：使用 .env.production；Compose 會先跑 migrate/bootstrap 再啟動 web
docker compose --env-file .env.production -f docker-compose-production.yml up -d

# 重新啟動 web 服務（改完程式碼後用這個）
docker compose --env-file .env.production -f docker-compose-production.yml restart web

# 查看 production migration log
docker compose --env-file .env.production -f docker-compose-production.yml logs migrate

# 連進資料庫查看資料
docker compose --env-file .env.production -f docker-compose-production.yml exec db psql -U meet -d meetdb

# 查看 web 服務 log
docker compose --env-file .env.production -f docker-compose-production.yml logs -f web

```

---

## 速率限制

為避免學生濫用 API，系統設有以下限制：

- 每個環節預設最多 **每小時 20 次** AI 呼叫
- 每位學生預設每天最多 **40 次** 外部 API 呼叫
- 上傳錄音檔最長 **5 分鐘**

部署者可透過 `STAGE_HOURLY_LIMIT`、`DAILY_API_LIMIT` 與 `MAX_AUDIO_SECONDS` 調整這些限制。

---

## 系統架構

```
瀏覽器（Bootstrap 5）
        │
FastAPI（port 7682）
  ├── /api/auth/*      JWT 登入驗證
  ├── /api/student/*   學生功能
  ├── /api/admin/*     管理員功能
  └── static/          HTML 靜態頁面
        │
PostgreSQL（port 5432，僅容器內部存取）
        ├── OpenAI（Whisper 語音辨識 + GPT 學習回饋 + TTS 語音合成）
        ├── Oracle Object Storage（儲存錄音）
        └── Outlook SMTP（寄發通知信）
```

---

## 常見問題

**Q：啟動後網站打不開？**

1. 確認防火牆有開放 7682 port：OCI Console → Networking → VCN → Security List → 新增 Ingress Rule，port 7682，TCP
2. 伺服器本機防火牆：`sudo ufw allow 7682`

**Q：`docker compose logs -f web` 顯示資料庫連線錯誤？**

通常是 `.env.production` 裡的 `DATABASE_URL` 密碼和 `POSTGRES_PASSWORD` 不一致，對照確認。

**Q：Alembic 說「Target database is not up to date」？**

```bash
docker compose --env-file .env.production -f docker-compose-production.yml run --rm migrate
```

**Q：更新程式碼後如何重新部署？**

```bash
git pull
docker compose --env-file .env.production -f docker-compose-production.yml pull
docker compose --env-file .env.production -f docker-compose-production.yml up -d
```

---

## 管理後台清理用量（手動）

如需手動清除某位學生當天的 API 用量：

```bash
docker compose --env-file .env.production -f docker-compose-production.yml exec db psql -U meet -d meetdb -c "
DELETE FROM api_usage_logs
WHERE user_id = <學生的user_id>
  AND called_at >= (NOW() AT TIME ZONE 'Asia/Taipei')::date;
"
```

---

## 貢獻、安全與授權

- 貢獻流程與測試方式：[CONTRIBUTING.md](CONTRIBUTING.md)
- 私人安全弱點通報：[SECURITY.md](SECURITY.md)
- 社群互動規範：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 第三方套件與容器元件：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- 建立乾淨公開上傳檔：[docs/open-source-release.md](docs/open-source-release.md)

除非檔案另有明確標示，本 repository 的原始碼與文件依 Apache License 2.0 提供。第三方依賴、遠端載入資產、基底映像與外部服務仍適用各自條款。
