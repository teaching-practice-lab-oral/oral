# AI 英語面試練習系統

幫助大學生練習英文面試的 AI 輔助平台。學生依序完成「欲應徵的職位 → 寫作練習 → 跟讀練習 → 角色扮演 → AI 回饋 → 心得撰寫」六個區段，老師（管理員）負責開放作業與正式批改。

本專案以 [Apache License 2.0](LICENSE) 開放原始碼。部署者需自行準備外部服務帳號，並負責學生資料告知、同意、保存、刪除及跨境傳輸等適用規範。本專案不附帶任何真實學生資料或可直接使用的服務憑證。

---

## 學生操作流程

| 區段 | 內容 |
|------|------|
| 1. 欲應徵的職位 | 設定目標職位、工作內容與所需職能，系統據此產生每題的個人化學習鷹架 |
| 2. 寫作練習 | 寫草稿 → 取得 AI 練習回饋 → 修改為最終稿 |
| 3. 跟讀練習 | 系統將最終稿轉成示範語音，學生跟讀並錄音上傳 |
| 4. 角色扮演 | AI 面試官提問 4 題核心題目，再加 1 題未預告的臨場追問 |
| 5. AI 回饋 | 整理整場面試的優勢與改進建議，不列入正式成績 |
| 6. 心得撰寫 | 對照作答與 AI 回饋完成反思，送出後由老師正式批改 |

每份作業最多可練習 3 次。

---

## 系統架構

```
瀏覽器（HTML／JavaScript，Bootstrap 5）
        │
FastAPI（gunicorn + uvicorn，容器內 port 7682）
  ├── /api/auth/*      登入與帳號
  ├── /api/student/*   學生功能
  ├── /api/admin/*     管理員功能
  └── /static/*        前端頁面
        │
        ├── PostgreSQL 15（僅容器內部存取）
        ├── S3 相容物件儲存（錄音、照片、成果包）
        ├── OpenAI（文字回饋、Whisper 語音辨識、TTS 語音合成）
        └── SMTP（帳號、提醒與成果通知信）
```

### 外部服務

| 項目 | 用途 |
|------|------|
| Docker 與 Docker Compose | 執行資料庫、遷移、備份與網站服務 |
| OpenAI API | 寫作回饋、角色扮演、語音辨識與語音合成 |
| S3 相容物件儲存 | 儲存學生錄音、心得照片與成果包（範例使用 Oracle Object Storage） |
| Cloudflare Turnstile | 登入頁防機器人驗證 |
| SMTP 信箱 | 寄送帳號、密碼重設、截止提醒與成果通知 |
| HTTPS 反向代理 | 正式環境必須以 HTTPS 網域對外服務 |

上述供應商只是目前的部署範例，不是 Apache-2.0 授權的一部分，也不代表只能使用這些供應商。

---

## 本機開發

本機環境以 Docker Compose 啟動，網址為 `http://localhost:7683`：

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # 貼到 .env 的 SECRET_KEY
docker compose up -d --build
```

啟動前把 `.env` 改成本機設定：`APP_ENV=development`、`PUBLIC_BASE_URL` 與 `CORS_ORIGINS` 設為 `http://localhost:7683`、`TRUSTED_HOSTS=localhost,127.0.0.1`；不使用的外部服務請清空範例憑證。

本機的 `docker-compose.yml` 固定讀取 `.env`，並把 `app/` 與 `alembic/` 掛載進容器，修改程式後重新啟動 `web` 即可。

開發時請勿使用真實學生資料，也不要把 `.env`、資料庫備份、匯出檔、錄音或照片提交到版本控制。

---

## 正式環境部署

以下以 Ubuntu 伺服器（範例為 OCI Ampere A1 ARM VM）為例。

### 1. 安裝 Docker

依 [Docker 官方文件](https://docs.docker.com/engine/install/ubuntu/) 安裝 Docker Engine 與 Compose plugin，然後讓目前使用者不需要 `sudo`：

```bash
sudo usermod -aG docker $USER   # 重新登入後生效
docker run hello-world          # 看到 Hello from Docker! 代表安裝成功
```

### 2. 下載專案並建置映像檔

正式環境的 Compose 只接受固定 digest 的映像檔，不會在伺服器上自行建置，也不接受可變動的 `:latest`。請在建置機器上建置並推送到你的 container registry：

```bash
git clone https://github.com/teaching-practice-lab-oral/oral.git
cd oral
docker buildx build --platform linux/arm64 -t <your-registry>/meet:<版本> --push .
docker buildx imagetools inspect <your-registry>/meet:<版本>   # 取得 sha256 digest
```

伺服器上同樣需要一份專案（Compose 檔與 `scripts/` 會被掛載使用）。

### 3. 準備物件儲存

以 Oracle Object Storage 為例：

1. OCI Console → Object Storage → **Create Bucket**，Visibility 選 **Private**。
2. Identity → Users → 你的帳號 → **Customer Secret Keys** → **Generate Secret Key**，記下 Access Key ID 與 Secret Access Key（Secret 只顯示一次）。
3. S3 端點格式為 `https://<namespace>.compat.objectstorage.<region>.oraclecloud.com`，namespace 可在 Object Storage 頁面看到。

### 4. 設定 Cloudflare Turnstile

Cloudflare Dashboard → Turnstile → **Add Site**，填入網域，記下 Site Key 與 Secret Key。

### 5. 設定環境變數

```bash
cp .env.example .env.production
nano .env.production
```

逐項填寫，不要留下範例假值。正式環境啟動時會檢查設定，以下項目缺少或格式不符時服務不會啟動：

| 設定 | 說明 |
|------|------|
| `POSTGRES_PASSWORD`、`DATABASE_URL` | 使用長亂數密碼；兩處的帳號、密碼與資料庫名稱必須一致 |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `OBJECT_STORAGE_NAMESPACE` | 8–64 字元，例如 `python3 -c "import secrets; print('oral-' + secrets.token_hex(12))"`。**每次重建資料庫都要換新值**，避免新資料覆寫物件儲存中的舊媒體 |
| `PUBLIC_BASE_URL` | 對外的 HTTPS 網址 |
| `CORS_ORIGINS`、`TRUSTED_HOSTS` | 明確列出正式網域，不可使用 `*` |
| `TURNSTILE_SECRET_KEY`、`TURNSTILE_SITE_KEY` | 第 4 步取得的金鑰 |
| `MEET_IMAGE` | 第 2 步取得的映像檔，格式為 `<registry>/meet@sha256:...` |
| `PROTECTED_ADMIN_STUDENT_ID` | 指定管理員的帳號，只有此帳號能修改評分規準、建立預設作業、解除全站登入限制等 |
| `OPENAI_API_KEY`、`OCI_*`、`MAIL_*` | 外部服務憑證；`MAIL_PASSWORD` 請填 SMTP 服務商核發的密碼 |

其餘項目（API 用量與上傳／匯出限流、資料保留天數、併發數）可沿用 [.env.example](.env.example) 的預設值。

### 6. 啟動服務

```bash
docker compose --env-file .env.production -f docker-compose-production.yml up -d
docker compose --env-file .env.production -f docker-compose-production.yml ps
```

啟動順序為：`db` → `migrate`（套用資料庫遷移、建立系統評分規準、執行 `alembic check`，完成後退出）→ `web`。另有 `pg_backup` 服務每天 03:00 備份資料庫到 `./pg_backup/`，保留 7 天。

`web` 在主機的 7682 port 提供服務。請以 HTTPS 反向代理（例如 Nginx、Caddy 或 Cloudflare Tunnel）將 `PUBLIC_BASE_URL` 的網域轉到 7682；系統只接受 `TRUSTED_HOSTS` 列出的網域，直接用 IP 連線會被拒絕。

資料庫遷移從 `001_current_schema_baseline` 開始，早於此 baseline 的舊資料庫不支援直接升級，需先備份再重建。

### 7. 建立第一個管理員帳號

```bash
docker compose --env-file .env.production -f docker-compose-production.yml exec web \
  python scripts/init_admin.py --name "系統管理員" --student-id admin001 --email admin@example.com
```

指令會要求輸入並確認密碼，輸入內容不會顯示，也不會留在 shell history。完成後到 `<PUBLIC_BASE_URL>/login` 登入。

之後的帳號請在管理後台的「使用者」頁新增或以 Excel 匯入，系統沒有公開的註冊頁面。若要使用五份預設作業，請以指定管理員登入，在「作業」頁按「建立預設五套作業」，再為各作業設定開放與截止日期。

### 更新版本

建置並推送新的映像檔（第 2 步），把 `.env.production` 的 `MEET_IMAGE` 換成新的 digest，然後：

```bash
git pull
docker compose --env-file .env.production -f docker-compose-production.yml up -d
```

`migrate` 會在 `web` 啟動前自動套用新的資料庫遷移。

---

## 維運

### 常用指令

以下指令都需要加上 `--env-file .env.production -f docker-compose-production.yml`，為簡潔起見以 `$PROD` 表示：

```bash
PROD="--env-file .env.production -f docker-compose-production.yml"

docker compose $PROD logs -f web          # 查看網站 log
docker compose $PROD logs migrate         # 查看資料庫遷移 log
docker compose $PROD restart web          # 重新啟動網站
docker compose $PROD run --rm migrate     # 手動重跑遷移與系統資料檢查（可重複執行）
docker compose $PROD exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'   # 進入資料庫
```

### 解除登入鎖定

同一帳號連續登入失敗 5 次會鎖定 15 分鐘；同一來源 IP 在 15 分鐘內失敗次數過多也會被暫時限制。

指定管理員可在「稽核」→「登入稽核」分頁按「一鍵解除登入限制」，會清除所有帳號的鎖定與來源 IP 的失敗計數；登入紀錄不會刪除，操作會記在「敏感操作」分頁。

### API 用量限制

| 設定 | `.env.example` 的值 | 說明 |
|------|------|------|
| `STAGE_HOURLY_LIMIT` | 20 | 每個階段每小時的 AI 呼叫次數 |
| `DAILY_API_LIMIT` | 40 | 每位學生每天的外部 API 呼叫次數（未設定時為 50） |
| `MAX_AUDIO_SECONDS` | 300 | 單一錄音的最長秒數 |

若需手動清除某位學生當天的 API 用量：

```bash
docker compose $PROD exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
DELETE FROM api_usage_logs
WHERE user_id = <學生的 user_id>
  AND called_at >= (NOW() AT TIME ZONE 'Asia/Taipei')::date;
SQL
```

---

## 常見問題

**網站打不開？**
確認反向代理已把網域轉到 7682，且雲端與主機防火牆（例如 OCI Security List、`ufw`）允許代理連到該 port。也請確認瀏覽器使用的網域有列在 `TRUSTED_HOSTS`。

**`web` 的 log 顯示資料庫連線錯誤？**
通常是 `DATABASE_URL` 中的帳號、密碼或資料庫名稱與 `POSTGRES_*` 不一致。

**`web` 沒有啟動？**
`web` 要等 `migrate` 成功才會啟動。執行 `docker compose $PROD logs migrate` 查看原因，常見的是缺少必要設定或 `OBJECT_STORAGE_NAMESPACE` 格式不符。

---

## 授權

除非檔案另有明確標示，本 repository 的原始碼與文件依 Apache License 2.0 提供。第三方依賴、遠端載入資產、基底映像與外部服務仍適用各自條款。
