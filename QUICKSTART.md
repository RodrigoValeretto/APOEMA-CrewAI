# ⚡ APOEMA - Quick Start Guide

Get started with APOEMA in 5 minutes!

## 🚀 Quick Setup

### 1. Clone & Enter Project
```bash
cd crewai-test
```

### 2. Install uv (Fast Dependency Manager)
```bash
# One-liner installer
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via pip
pip install uv
```

### 3. Install Dependencies & Create Virtual Environment
```bash
# Install with Makefile (recommended - simplest)
make install

# Or manually with uv
uv sync
```

### 4. Configure API Key
Get your free Google Gemini API key from [ai.google.dev](https://ai.google.dev):

```bash
# Linux/Mac
export GEMINI_API_KEY="your-api-key-here"

# Windows PowerShell
$env:GEMINI_API_KEY="your-api-key-here"

# Windows CMD
set GEMINI_API_KEY=your-api-key-here
```

## ⚡ How APOEMA-CrewAI Works

APOEMA-CrewAI analyzes post-graduation programs against CAPES evaluation criteria by analyzing assessment documents and validating program reports in 2 or 3 stages:

### Execution Modes

APOEMA supports two execution modes:

- **Flow Mode** (default): Modern event-driven workflow using CrewAI Flows for better state management and control flow
- **Crew Mode**: Traditional sequential execution using CrewAI Crews

```bash
make run assessment-file=cc_assessment_data.json                    # Uses Flow mode (default)
make run assessment-file=cc_assessment_data.json exec-mode=crew     # Uses Crew mode
make run assessment-file=cc_assessment_data.json exec-mode=flow     # Explicitly use Flow mode
```

### Stage 1: Assessment Analysis (Required)
```bash
make run assessment-file=cc_assessment_data.json
```
- Loads the assessment criteria for your area of study in CAPES classification
- Uses LLM to analyze and extract insights from the assessment
- Generates structured report of evaluation criteria and expectations
- **Output:** `output/output_YYYYMMDDHHMMSS.md`

### Stage 2A: PDF Validation (Optional - Alternative 1)
```bash
make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf
```
- Takes the assessment criteria from Stage 1
- Analyzes plots/visualizations from APOEMA-generated PDF report
- Checks if program data meets assessment standards
- Validates that plots are appropriate for the area of study
- **Outputs:** 
  - `output/output_YYYYMMDDHHMMSS.md` (assessment analysis)
  - `output/conformance_report_YYYYMMDDHHMMSS.md` (validation results)
  - `output/utility_assessment_YYYYMMDDHHMMSS.md` (plot utility analysis)

### Stage 2B: PNG+CSV Analysis (Optional - Alternative 2)
```bash
make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv
```
- Takes the assessment criteria from Stage 1
- Analyzes a PNG plot image with corresponding CSV data
- Extracts technical metrics and statistical insights
- Validates relevance to the evaluation area and CAPES criteria
- **Outputs:**
  - `output/output_YYYYMMDDHHMMSS.md` (assessment analysis)
  - `output/plot_insights_YYYYMMDDHHMMSS.md` (plot analysis and insights)
  - `output/plot_importance_YYYYMMDDHHMMSS.md` (relevance assessment)

### Custom Output Prefix (Optional)
```bash
make run assessment-file=cc_assessment_data.json prefix=cc_analysis
```
- Changes output file prefix from timestamp to custom name
- Useful for organizing multiple analyses

### Examples
```bash
# Assessment analysis only (Flow mode - default)
make run assessment-file=cc_assessment_data.json

# Assessment analysis (Crew mode)
make run assessment-file=cc_assessment_data.json exec-mode=crew

# With PDF report validation (Flow mode)
make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf

# With PDF report validation (Crew mode)
make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf exec-mode=crew

# With PNG plot and CSV data analysis (Flow mode)
make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv

# With PNG plot and CSV data analysis (Crew mode)
make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv exec-mode=crew

# Full example with custom prefix and Flow mode
make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv prefix=my_analysis

# Full example with custom prefix and Crew mode
make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf prefix=cc_analysis exec-mode=crew
```

## 📖 Next Steps

- Read [README.md](./README.md) for detailed documentation
- Check [REPORT_ANALYZER_GUIDE.md](./REPORT_ANALYZER_GUIDE.md) for advanced usage
- View generated reports in `output/` directory

## 🆘 Troubleshooting

**API Key not working?**
```bash
echo $GEMINI_API_KEY  # Verify it's set
```

**Module not found?**
```bash
uv sync  # Reinstall dependencies
```

**PDF not found?**
```bash
# Use absolute path or relative from project root
uv run python main.py ./reports/my-report.pdf
```

## 📊 Example Workflow

```bash
# 1. Install dependencies
make install

# 2. Analyze assessment data for your area of study
make run assessment-file=cc_assessment_data.json

# 3. Check results
cat output/output_*.md

# 4A. If you have a program report, validate it against assessment
make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf

# 4B. OR if you have a PNG plot with CSV data
make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv

# 5. Review analysis results
cat output/conformance_report_*.md  # For PDF analysis
cat output/plot_insights_*.md       # For PNG+CSV analysis

# 6. Clean up generated files
make clean
```

## 💡 Tips

- **assessment_data.json is required:** This defines your area of study in CAPES classification and the evaluation criteria
- **pdf-file is optional:** Use it to validate a program's PDF report against the assessment standards
- **png-file and csv-file are optional:** Use them together to analyze a specific plot with its underlying data (alternative to PDF)
- **prefix is optional:** Defaults to timestamp, use it to organize multiple analyses
- **PDF and PNG+CSV are alternatives:** Provide either PDF OR (PNG + CSV), not both
- **Check output/:** All results are timestamped or prefixed in this directory
- **uv is fast:** Dependency resolution and installation in seconds!

## 🛠️ Advanced uv Usage

### Activate the Virtual Environment Directly
```bash
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate      # Windows
```
Then run commands normally: `python main.py --pdf-file report.pdf`

### Add a New Dependency
```bash
uv add package-name          # Production dependency
uv add --dev package-name    # Development dependency
```

### Update Dependencies
```bash
uv sync --upgrade  # Update all packages
```

## 📄 Document Conversion (Fichas CAPES → JSON, via API)

Since the `json-converter` branch, fichas (PDF) and anexos/adendos (XLSX) can be
uploaded through the API, converted to enriched JSON in the background (Dramatiq
`conversion` queue + docling) and grouped under an **informativo** (area corpus).
Analyses can then be triggered straight from the informativo:

```bash
# 1) Create the informativo once
curl -X POST http://localhost:8000/api/informativos \
  -H "Content-Type: application/json" \
  -d '{"nome": "Ciência da Computação", "quadrienio": "2025-2028"}'

# 2) Upload the ficha PDF (kind=ficha) and any xlsx anexos (kind=anexo|adendo)
curl -X POST http://localhost:8000/api/informativos/1/documentos \
  -F "file=@COMPUTACAO_FICHA_2025_2028.pdf" -F "kind=ficha"

# 3) Wait until GET /api/informativos/1/documentos shows status "completed"
#    (poll every ~10s; each PDF takes ~10-90s on the converter worker)

# 4) Run the analysis from the informativo (ficha = assessment, anexos = Knowledge)
curl -X POST http://localhost:8000/api/analysis \
  -H "Content-Type: application/json" \
  -d '{"informativo_id": 1, "model": "gemini"}'
```

The converted JSON is stored at `uploads/converted/doc_{id}.json` and registered
in `analysis_files` (file_type `assessment` for fichas, `anexo` otherwise), so it
can also be reused directly via `assessment_file_id`.

## 💻 Using Commands Without Makefile

If you prefer to skip the Makefile, you can use uv directly:

```bash
# Install
uv sync

# Run with arguments
uv run python main.py --pdf-file ./reports/report.pdf
uv run python main.py --assessment-file custom.json --prefix my_analysis
```

---

**Need help?** See [README.md](./README.md) for full documentation.
