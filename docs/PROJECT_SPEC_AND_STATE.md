# 實驗室藥品安全管理系統（Laboratory Chemical Safety System, LCSS）— 完整需求、架構規格與開發狀態檔

> **文件用途**：本文件為「單一真實來源（Single Source of Truth）」，提供後續 AI 開發代理（Agents）或工程師直接依據本規格進行專案初始化、模組實作、測試與打包。
> **最後更新**：2026-11-26
> **目標平台**：Windows 10 / 11（主要）、跨平台相容（Python + Qt6）
> **架構路線**：方案 C（Python + PySide6 原生桌面軟體 + SQLite + 可選配 Ollama）

---

## 0. 專案當前狀態（Agent State Machine）

```yaml
project_name: Laboratory Chemical Safety System
short_name: LCSS
current_phase: PHASE_7_MVP_COMPLETE
code_generated: true
active_milestone: COMPLETED_M1_TO_M7
blocking_issues: []
```

### 開發里程碑檢查清單（供後續代理即時更新）
- [x] **M1 專案骨架與資料層**：`pyproject.toml`、目錄結構、SQLite + SQLAlchemy 2.0 ORM 模型、離線種子資料（CAMEO 基團矩陣、GHS 圖示、常用藥品範例）
- [x] **M2 化學品解析與快取 (`ChemResolver`)**：CAS 驗證、PubChem PUG-REST/PUG-View 抓取、台灣勞動部 GHS 爬蟲／對應、本地 SQLite 快取
- [x] **M3 相容性檢查引擎 (`CompatibilityEngine`)**：NOAA CAMEO 反應基團矩陣查詢 + RDKit SMARTS 官能基自動分類 + 單元測試
- [x] **M4 SDS 生成與標籤模組 (`SDSGenerator`)**：GHS 16 大項繁中 HTML→PDF 生成（Qt `QPrinter` / `ReportLab`）、原廠 PDF 匯入與 `PyMuPDF` 解析、瓶身／自配試劑標籤（含 QR Code）
- [x] **M5 Local LLM 輔助服務 (`LocalLLMService`)**：Ollama REST API 整合（翻譯、原廠 SDS PDF 結構化萃取、中文風險建議）與離線優雅降級
- [x] **M6 PySide6 桌面介面與背景執行緒**：主視窗、5 大功能頁籤、N×N 相容性矩陣互動表、入庫防呆彈窗、`QThreadPool` 非同步任務層
- [x] **M7 安裝引導程式與首次啟動精靈**：Windows 安裝引導腳本／Bootstrapper（檢查 Python/uv、自動建立 `.venv`、安裝依賴、建捷徑）＋ PySide6 `QWizard` 首次設定精靈

---

## 1. 專案背景與核心設計紅線

### 1.1 應用情境
本軟體定位為**通用型實驗室藥品安全管理系統**，並特別兼顧台灣教學／研究實驗室（含高中至大學分子生物與化學實驗室）之實務管理需求，包含：
- 原裝藥品與「自配／分裝試劑」全生命週期管理。
- 符合台灣勞動部《危害性化學品標示及通識規則》之繁體中文 16 大項 SDS 與 GHS 標示。
- 強化相容性儲存防呆（如酸鹼分離、漂白水/次氯酸鈉禁混酸、氧化劑禁混有機溶劑等）與禁用／管制試劑標示。

### 1.2 核心安全與工程紅線（嚴格遵守）
1. **安全決策確定性原則（Deterministic-First）**：
   - GHS 危害分類、H/P 語句、化學品相容性判定，**必須**以權威資料庫（PubChem / 台灣 GHS / NOAA CAMEO）與確定性演算法（RDKit SMARTS 規則）為唯一依據。
   - **嚴禁**僅由 Local LLM 憑空推斷化學品相容性或編造 SDS 毒理／物化數據。
2. **Local LLM 輔助與優雅降級（Graceful Degradation）**：
   - Ollama 僅負責「英翻繁中、原廠 PDF 欄位結構化萃取、白話安全摘要」。
   - 若使用者未安裝或未啟動 Ollama，所有核心功能（庫存、CAS 查詢、相容性檢查、16 節 SDS PDF 生成）皆須 **100% 正常運作**。
3. **法規免責與來源標註**：
   - 系統自動生成之 SDS PDF 頁首／頁尾須清楚標註「**系統彙整內部參考版（資料來源：PubChem / 台灣 GHS，正式法規依據請以供應商原廠 SDS 為準）**」，並提供「歸檔原廠 PDF」欄位。
4. **桌面介面零卡頓原則（Non-Blocking UI）**：
   - 所有網路請求、爬蟲、RDKit 批次運算、PDF 匯出、Ollama 推論，皆須在 `QThread` / `QThreadPool` 背景執行，透過 Qt Signal/Slot 回報進度與結果，禁止阻塞主執行緒。

---

## 2. 技術選型規格（方案 C：原生桌面應用）

| 層級 | 選定技術 / 套件 | 版本要求 | 選用理由與避坑說明 |
| :--- | :--- | :--- | :--- |
| **語言** | Python | `>=3.11, <3.13` | `rdkit` 與 `PySide6` 在 3.11/3.12 輪子（wheel）最完整穩定。 |
| **套件管理** | `uv`（優先）或 `pip` + `venv` | `uv >= 0.4` | 未來安裝引導程式透過 `uv` 建立虛擬環境速度極快且可鎖定版本。 |
| **GUI 框架** | `PySide6`（可選配 `PySide6-Fluent-Widgets`） | `>=6.7` | LGPL 授權友善、原生 Qt6 效能與高 DPI 支援。 |
| **資料庫** | `SQLite` + `SQLAlchemy 2.0` | `>=2.0` | 單檔免伺服器；ORM 解耦，未來換 PostgreSQL 零痛點。 |
| **資料驗證** | `Pydantic v2` | `>=2.7` | 定義核心模組間的資料契約（Data Contracts）與設定檔驗證。 |
| **化學核心** | `rdkit` | `>=2024.3` | 離線解析 SMILES、SMARTS 官能基比對、繪製 2D 分子結構圖。 |
| **網路與爬蟲** | `httpx` + `beautifulsoup4` + `lxml` | `httpx >= 0.27` | 支援同步/非同步、逾時與重試控管，抓取 PubChem 與台灣 GHS。 |
| **SDS PDF 生成** | **Qt 內建 `QTextDocument` + `QPrinter`** 或 `ReportLab` + `Jinja2` | `Jinja2 >= 3.1` | **Windows 避坑**：禁止使用 `WeasyPrint`（Windows 上需大量 GTK/Pango DLL，安裝與打包極易失敗）。優先用 `Jinja2` 渲染 HTML 再交由 Qt `QPrinter` 輸出 PDF，原生支援 Windows 繁體中文字型（微軟正黑體 / 思源黑體）。 |
| **原廠 PDF 讀取** | `PyMuPDF` (`fitz`) | `>=1.24` | 高速擷取供應商 SDS PDF 文字與頁面縮圖預覽。 |
| **條碼與標籤** | `qrcode[pil]` + `python-barcode` | 最新穩定版 | 產出瓶身 QR Code 與條碼圖片嵌入標籤 PDF。 |
| **Local LLM** | `Ollama`（透過 `httpx` 呼叫 REST API） | 本機選配 | 預設端點 `http://localhost:11434`，推薦模型 `qwen2.5:7b` / `gemma2:9b`。 |
| **測試框架** | `pytest` + `pytest-qt` + `respx` | 最新穩定版 | 單元測試、UI 測試與 HTTP API Mock 測試。 |

---

## 3. 完整 MVP 功能需求規格（Functional Requirements）

### FR-1：藥品庫存與生命週期管理
1. **化學品主檔與庫存品項分離**：
   - **化學品主檔（`Chemical`）**：以 `CAS Number` 為唯一鍵，記錄中英文品名、分子式、分子量、SMILES、InChIKey、GHS 危害圖示、H/P 語句、CAMEO 反應基團、管制等級（一般／教師專管／禁用）。
   - **實體庫存（`InventoryItem`）**：每一瓶／每一批號為獨立紀錄，包含類型（`原裝試劑` / `自配或分裝試劑`）、廠牌與批號、容器容量與目前剩餘量、單位、存放位置、開封日、有效期限、自配資訊（濃度、配製者、配製日期、母液來源 ID）、條碼／UUID。
2. **階層式存放位置（`StorageLocation`）**：
   - 支援三層結構：`實驗室/區域` → `藥品櫃`（標註櫃體屬性：防火易燃櫃、耐酸鹼櫃、一般常溫櫃、4°C 冰箱、-20°C 冷凍庫、毒化物專櫃）→ `層架/隔間`。
3. **異動紀錄與提醒**：
   - 記錄入庫、領用、移櫃、盤點修正、報廢（含操作者、時間、數量變化、備註）。
   - 支援 USB 條碼掃描槍（鍵盤模擬輸入）快速搜尋與領用。
   - 首頁儀表板自動標示：即期／過期藥品（預設 30 天內）、低庫存警示、櫃位存在不相容衝突警示。

### FR-2：化學品資料解析與離線快取 (`ChemResolver`)
1. **查詢流程**：輸入 CAS Number（自動檢核校驗碼 Checksum）或中英文品名 → 優先查詢本地 SQLite `chemicals` 快取 → 若未命中或使用者點選「線上更新」，於背景連線查詢外部資料庫並回寫快取。
2. **資料來源優先序**：
   - **PubChem PUG-REST**：取得 CID、IUPAC 名稱、分子式、分子量、Canonical SMILES、InChIKey。
   - **PubChem PUG-View (GHS & LCSC/ICSC)**：取得 GHS Pictograms (`GHS01`–`GHS09`)、Signal Word（危險/警告）、H-Statements、P-Statements、物化性質、急救與滅火要點。
   - **台灣勞動部 GHS 網站（`ghs.osha.gov.tw`）**：以 CAS 查詢繁體中文品名、危害分類與中文 H/P 語句（需具備容錯與本地 H/P 代碼對照表備援，避免官網改版導致崩潰）。
3. **本地靜態字典備援**：
   - 內建完整 **GHS H-codes（H200–H433）與 P-codes（P101–P503）繁體中文官方對照表**（JSON），即使僅抓到英文代碼，也能 100% 離線正確映射出台灣法規繁體中文語句。

### FR-3：物質安全資料表（SDS）生成與標籤列印 (`SDSGenerator`)
1. **標準 16 大項 SDS PDF 生成**：
   - 依據台灣 GHS 規範生成完整 16 節內容：
     1. 化學品與廠商資料（自動帶入實驗室緊急聯絡電話）
     2. 危害辨識資料（自動嵌入對應 GHS01–GHS09 向量圖示、警示語、H/P 語句）
     3. 成分辨識資料（CAS、分子式、分子量）
     4. 急救措施　5. 滅火措施　6. 洩漏處理方法　7. 安全處置與儲存方法（帶入相容性禁忌摘要）
     8. 暴露預防措施（PPE 建議）　9. 物理及化學性質　10. 安定性及反應性
     11. 毒性資料　12. 生態資料　13. 廢棄處置方法　14. 運送資料　15. 法規資料　16. 其他資料（來源與免責聲明）。
   - 支援在介面上即時編輯／微調任何欄位後再匯出 PDF。
2. **原廠 SDS PDF 歸檔與解析**：
   - 支援將供應商 PDF 複製歸檔至本地 `storage/sds_files/` 並與化學品關聯，可於軟體內一鍵開啟或預覽。
   - 提供「匯入原廠 PDF 並擷取欄位」功能（`PyMuPDF` 抽字 + 可選 Ollama 結構化抽取）。
3. **標籤列印（PDF 匯出）**：
   - **GHS 危害標示瓶身標籤**（品名、CAS、GHS 圖示、警示語、主要危害、QR Code）。
   - **自配／分裝試劑標籤**（品名、濃度、配製者、配製日期、有效期限、危害圖示、QR Code）。

### FR-4：化學品相容性檢查引擎 (`CompatibilityEngine`)
1. **雙層確定性判定引擎**：
   - **第一層（精確對照）**：內建離線 `data/cameo_cas_map.json`（常見實驗室化學品 CAS → NOAA CAMEO Reactive Group IDs，至少預收錄 200+ 種常見教學／分生／化學實驗室試劑，含漂白水/次氯酸鈉、鹽酸、硫酸、硝酸、醋酸、氫氧化鈉、氨水、乙醇、異丙醇、丙酮、氯仿、酚、雙氧水、疊氮化鈉、胍鹽等）。
   - **第二層（RDKit SMARTS 結構推斷）**：當化學品不在對照表中且具有 `SMILES` 時，使用 `rdkit.Chem.MolFromSmiles` 與 `data/smarts_reactive_groups.json` 進行子結構比對，自動歸類所屬反應基團（如強酸、強鹼、氧化劑、過氧化物、鹵代烴、易燃醇酮醚、胺類、疊氮化物、氰化物等），並標記推斷來源為 `RDKIT_INFERRED`。
   - **相容性矩陣（`data/cameo_matrix.json`）**：定義兩兩反應基團之交互結果，分三級：
     - `COMPATIBLE`（綠燈）：無已知劇烈不相容反應。
     - `CAUTION`（黃燈）：視濃度／溫度條件具潛在風險，建議隔離。
     - `INCOMPATIBLE`（紅燈）：禁止混放或混用，並列出具體危害標籤（`HEAT` 劇烈放熱、`TOXIC_GAS` 產生有毒氣體、`FIRE` 起火、`EXPLOSION` 爆炸、`POLYMERIZATION` 劇烈聚合）與原因說明。
   - **櫃體相容性加檢**：檢查藥品性質與目標櫃體類型是否匹配（例如：易燃液體不可放入一般非防爆冰箱）。
2. **兩大使用情境**：
   - **入庫／移櫃即時防呆**：選擇目標層架時自動執行與該層現有所有庫存之兩兩比對，若有 `INCOMPATIBLE` 或 `CAUTION`，跳出顯眼警告對話框，需管理員填寫確認理由方可強制寫入（並留存日誌）。
   - **自由配伍檢查器（N × N 矩陣）**：使用者可從庫存或輸入 CAS 勾選 2～15 種藥品，即時渲染彩色 N × N 互動矩陣表格，點擊任一紅／黃燈儲存格顯示詳細危害機制與隔離建議。

### FR-5：Local LLM 輔助服務 (`LocalLLMService`)
1. **連線設定**：支援設定 Ollama Host（預設 `http://localhost:11434`）、模型選擇（自動呼叫 `/api/tags` 列出本機已安裝模型）、連線測試按鈕、功能總開關。
2. **三項 AI 輔助能力**（均採嚴格 Prompt 與 JSON Schema 驗證）：
   - `translate_sds_fields`：將 PubChem 英文安全欄位翻譯為自然且專業的台灣繁體中文。
   - `extract_sds_from_pdf_text`：從 `PyMuPDF` 抽取的原廠 SDS 文字中，萃取結構化 JSON 供新建藥品預填。
   - `summarize_compatibility_advice`：將 CAMEO 矩陣產出的英文危害代碼與機制，轉寫為簡明中文分櫃建議與溢漏應變重點（**不可更改**引擎判定的紅／黃／綠燈等級）。

---

## 4. 安裝程式與虛擬環境引導架構（針對需求 2）

為滿足「未來打包發佈後，能引導一般使用者自動安裝與建立獨立虛擬環境」之需求，採**兩階段引導架構**：

### 階段 A：Windows 安裝引導程式（`installer/`）
提供兩種發行包裝模式（MVP 先實作模式 1，並預留模式 2 腳本）：
1. **輕量級引導安裝程式（`LCSS_Setup.exe`，由 Inno Setup 或 PowerShell + 小型啟動器打包）**：
   - **Step 1 環境偵測**：檢查使用者電腦是否已有 `uv` 或相容 Python（3.11/3.12）。
   - **Step 2 自動佈署 Runtime**：若皆未安裝，由引導介面詢問使用者同意後，自動下載並安裝獨立的 `uv` 執行檔（單一 binary，不汙染系統 PATH）並執行 `uv python install 3.12`。
   - **Step 3 建立虛擬環境**：於安裝目錄（預設 `%LOCALAPPDATA%\LCSS\`）自動執行 `uv venv .venv` 與 `uv sync --frozen`（若為離線版安裝包則指向內附 `wheelhouse/` 離線安裝），並即時顯示安裝進度與日誌。
   - **Step 4 建立啟動器與捷徑**：產生桌面與開始功能表捷徑，指向靜默啟動器（不閃黑窗，自動以 `.venv\Scripts\pythonw.exe main.py` 啟動主程式）。
2. **進階完全獨立封裝（選配）**：保留 `pyinstaller.spec` 範本供完全無網路且不可安裝套件之環境使用。

### 階段 B：首次啟動設定精靈（`ui/setup_wizard.py`，PySide6 `QWizard`）
程式首次啟動（偵測 `config/settings.json` 不存在或 `initialized == false`）時自動開啟：
1. **歡迎頁與環境健康檢查**：顯示 Python 版本、虛擬環境路徑、RDKit 可用狀態、SQLite 資料庫路徑。
2. **實驗室基本資訊與緊急聯絡網**：輸入實驗室名稱、負責人、校安／緊急聯絡電話（自動寫入設定並帶入未來生成之 SDS 第 1 節）。
3. **初始化藥品櫃範本**：讓使用者勾選欲預建的標準櫃位（如「防火易燃櫃」、「耐酸鹼腐蝕櫃」、「一般藥品櫃」、「4°C 試劑冰箱」），並可選擇是否匯入「常見教學實驗室示範藥品」方便立即體驗。
4. **Local LLM（Ollama）選配引導**：
   - 自動偵測 `http://localhost:11434` 是否存活。
   - 若已安裝：列出本機可用模型供選擇。
   - 若未安裝：提供下載連結與說明，以及顯眼的**「略過，先以純離線規則模式使用」**按鈕。

---

## 5. 系統分層架構與目錄規劃

```text
lab_safety_app/
├── pyproject.toml                  # 專案依賴與 uv / pytest 設定
├── main.py                         # 應用程式入口（檢查首次精靈 → 啟動主視窗）
├── app/
│   ├── __init__.py
│   ├── config.py                   # Pydantic Settings（路徑、Ollama、緊急聯絡資訊）
│   ├── schemas.py                  # 共用資料契約（Pydantic models / Enums）
│   ├── db/
│   │   ├── database.py             # SQLite Engine / SessionLocal / init_db
│   │   ├── models.py               # SQLAlchemy 2.0 ORM 資料表定義
│   │   └── repository.py           # CRUD 與進階查詢封裝
│   ├── core/
│   │   ├── chem_resolver.py        # CAS 檢核 + PubChem + 台灣 GHS 解析與快取
│   │   ├── compatibility.py        # CAMEO 矩陣 + RDKit SMARTS 相容性引擎
│   │   ├── sds_generator.py        # 16 節 SDS HTML→PDF 與瓶身/自配標籤生成
│   │   ├── pdf_parser.py           # PyMuPDF 原廠 SDS 文字擷取與縮圖
│   │   └── llm_service.py          # Ollama REST API 封裝與降級處理
│   └── ui/
│       ├── main_window.py          # 主視窗與左側導覽列
│       ├── setup_wizard.py         # 首次啟動精靈 (QWizard)
│       ├── workers.py              # QRunnable / QThreadPool 非同步任務與信號
│       ├── widgets/                # 可重用元件（GHS 圖示列、分子結構預覽、警告彈窗）
│       └── views/
│           ├── dashboard_view.py   # 儀表板（即期/低庫存/櫃位衝突總覽）
│           ├── inventory_view.py   # 藥品庫存管理與入庫/領用/自配表單
│           ├── compatibility_view.py # 櫃位安全檢視 + N×N 自由配伍矩陣
│           ├── sds_view.py         # SDS 編輯預覽、PDF 匯出、標籤列印、原廠上傳
│           └── settings_view.py    # Ollama 設定、備份還原、實驗室資訊
├── data/                           # 內建唯讀離線資源
│   ├── cameo_groups.json           # NOAA CAMEO Reactive Groups 定義
│   ├── cameo_matrix.json           # 基團兩兩相容性矩陣與危害代碼
│   ├── cameo_cas_map.json          # 200+ 常見實驗室藥品 CAS → CAMEO 基團對照
│   ├── smarts_reactive_groups.json # RDKit SMARTS 官能基 → CAMEO 基團推斷規則
│   ├── ghs_hp_zh_tw.json           # 繁體中文 H/P 語句官方對照表
│   ├── ghs_pictograms/             # GHS01.svg ~ GHS09.svg
│   └── templates/
│       ├── sds_16_sections.html    # 16 大項 SDS Jinja2 模板
│       └── bottle_label.html       # 瓶身／自配試劑標籤 Jinja2 模板
├── installer/                      # Windows 安裝與虛擬環境引導
│   ├── bootstrap.ps1               # 自動檢查/安裝 uv + Python + .venv + 建捷徑
│   ├── launch.vbs                  # 無黑窗啟動 .venv\Scripts\pythonw.exe
│   └── setup.iss                   # Inno Setup 安裝精靈腳本
└── tests/
    ├── test_chem_resolver.py
    ├── test_compatibility.py
    ├── test_sds_generator.py
    ├── test_repository.py
    └── test_ui_smoke.py
```

---

## 6. 核心資料庫 Schema 與模組資料契約

### 6.1 SQLite 資料表設計（`app/db/models.py`）
1. **`chemicals`（化學品主檔與快取）**
   - `id` (PK), `cas_number` (Unique, Indexed), `name_zh`, `name_en`, `formula`, `molecular_weight`, `smiles`, `inchikey`
   - `ghs_pictograms` (JSON list, e.g. `["GHS02", "GHS07"]`), `signal_word` (`危險`/`警告`/`None`)
   - `h_codes` (JSON list), `p_codes` (JSON list)
   - `reactive_groups` (JSON list of CAMEO group IDs), `group_source` (`CAMEO_DB` / `RDKIT_INFERRED` / `MANUAL`)
   - `control_level` (`NORMAL` / `TEACHER_ONLY` / `PROHIBITED`)
   - `sds_json` (JSON, 儲存 16 節結構化文字內容), `data_source`, `updated_at`
2. **`storage_locations`（存放位置）**
   - `id` (PK), `lab_name`, `cabinet_name`, `shelf_name`, `cabinet_type` (`FLAMMABLE` / `CORROSIVE` / `GENERAL` / `FRIDGE_4C` / `FREEZER_M20` / `TOXIC`), `notes`
3. **`inventory_items`（實體庫存瓶）**
   - `id` (PK), `chemical_id` (FK → `chemicals.id`), `location_id` (FK → `storage_locations.id`)
   - `barcode` (Unique, Indexed), `item_type` (`COMMERCIAL` / `PREPARED`)
   - `brand`, `lot_number`, `concentration`, `prepared_by`, `parent_item_id` (Nullable FK)
   - `capacity`, `current_quantity`, `unit`, `opened_date`, `expiry_date`, `status` (`IN_STOCK` / `EMPTY` / `DISPOSED`)
   - `created_at`, `updated_at`
4. **`inventory_logs`（異動與防呆覆寫日誌）**
   - `id` (PK), `item_id` (FK), `action` (`CHECK_IN` / `CHECK_OUT` / `MOVE` / `ADJUST` / `DISPOSE`), `delta_quantity`, `from_location_id`, `to_location_id`, `operator`, `override_warning_reason`, `timestamp`
5. **`sds_documents`（歸檔 PDF 紀錄）**
   - `id` (PK), `chemical_id` (FK), `doc_type` (`SUPPLIER_OFFICIAL` / `GENERATED_DRAFT`), `file_path`, `supplier_name`, `revision_date`, `uploaded_at`

### 6.2 核心介面資料契約（`app/schemas.py`）
後續代理實作時須遵循以下介面回傳型別，確保跨模組整合零衝突：
- `CompatibilityLevel(Enum)`: `COMPATIBLE`, `CAUTION`, `INCOMPATIBLE`, `UNKNOWN`
- `CompatibilityIssue(BaseModel)`:
  - `chem_a_cas: str`, `chem_b_cas: str`, `level: CompatibilityLevel`
  - `hazards: list[str]`（如 `["TOXIC_GAS", "HEAT"]`）
  - `matched_groups: list[tuple[str, str]]`
  - `summary_zh: str`, `recommendation_zh: str`, `inference_note: str`
- `SDSPayload(BaseModel)`: 對應 16 大項結構化欄位，可直接由 `ChemResolver` 產生、由 UI 編輯、由 `LocalLLMService` 翻譯補強、並交給 `SDSGenerator` 渲染為 PDF。

---

## 7. 給後續開發代理的執行指令與驗收標準

### 執行順序建議
1. **先建環境與 M1**：建立 `pyproject.toml` 與完整目錄，初始化離線 JSON 資料檔（務必確保 `cameo_matrix.json`、`cameo_cas_map.json`、`smarts_reactive_groups.json`、`ghs_hp_zh_tw.json` 結構完整且通過 JSON Schema 驗證）。
2. **實作並單獨測試 M2–M5**：每完成一個 `core/` 模組即撰寫對應 `pytest` 單元測試（網路 API 與 Ollama 需用 `respx` Mock，確保 CI／離線環境皆可跑通）。
   - **必測相容性安全案例**：
     - 次氯酸鈉（漂白水 `7681-52-9`）＋ 鹽酸（`7647-01-0`）→ 必須判定 `INCOMPATIBLE` 且含 `TOXIC_GAS`（氯氣）。
     - 濃硝酸（`7697-37-2`）＋ 乙醇（`64-17-5`）→ 必須判定 `INCOMPATIBLE` 且含 `FIRE` / `EXPLOSION`。
     - 未知 CAS 但提供過氧化物／疊氮化物 SMILES → 必須由 RDKit SMARTS 成功觸發對應反應基團警告。
3. **實作 M6（PySide6 UI）**：串接 `core/` 與 `db/`，所有耗時動作掛載至 `ui/workers.py`，並執行 `pytest-qt` 冒煙測試驗證主視窗啟動與核心流程。
4. **實作 M7（安裝引導與首次精靈）**：完成 `ui/setup_wizard.py` 與 `installer/bootstrap.ps1`、`installer/setup.iss`，並確認全新目錄下執行 `bootstrap.ps1` 可自動建立 `.venv` 並啟動軟體。
5. **更新狀態檔**：每完成一個里程碑，請回頭更新本文件第 0 節的 `active_milestone` 與檢查清單。
