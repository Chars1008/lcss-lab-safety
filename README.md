# 實驗室藥品安全管理系統（Laboratory Chemical Safety System, LCSS）

通用型實驗室藥品安全管理系統（Python + PySide6 + SQLite + 可選配 Ollama），兼顧台灣教學／研究實驗室（含高中至大學分子生物與化學實驗室）之實務管理需求。

## 核心特色
- **藥品庫存與生命週期管理**：化學品主檔（CAS 唯一鍵）與實體庫存瓶（原裝 / 自配分裝）分離，支援階層式櫃位、USB 條碼槍、即期與低庫存提醒。
- **化學品解析與離線快取 (`ChemResolver`)**：CAS 校驗碼驗證、PubChem PUG-REST/PUG-View、台灣勞動部 GHS 查詢與完整本地 H/P 語句繁中對照備援。
- **雙層確定性相容性引擎 (`CompatibilityEngine`)**：NOAA CAMEO 反應基團矩陣 + RDKit SMARTS 官能基自動推斷，支援入庫防呆與 N×N 自由配伍檢查。
- **16 大項繁中 SDS 與標籤列印 (`SDSGenerator`)**：Jinja2 + Qt `QPrinter` 原生輸出繁體中文 16 節 SDS PDF、GHS 瓶身標籤與自配試劑標籤（含 QR Code）。
- **Local LLM 輔助與優雅降級 (`LocalLLMService`)**：選配 Ollama 進行英翻繁中、原廠 PDF 結構化萃取與風險摘要；未安裝時所有核心功能仍 100% 離線正常運作。
- **Windows 安裝引導與首次啟動精靈**：`installer/bootstrap.ps1` 與 `ui/setup_wizard.py`。

## 快速開始（開發環境）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python main.py
```

## 執行測試

```powershell
pytest
```
