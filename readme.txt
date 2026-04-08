WINDOWS INSTALL
git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm install
cd ..

WINDOWS TERMINAL NOTE (POWERSHELL VS CMD)
PowerShell (inside project folder):
.\build_exe_windows.ps1 -Target Tool
.\build_exe_windows.ps1 -Target Viewer

CMD (inside project folder):
powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Tool
powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Viewer

WINDOWS RUN ANALYSIS
run_app.bat

WINDOWS RUN VIEWER
run_viewer.bat

WINDOWS AI PREREQUISITE
Install Ollama from https://ollama.com (external system dependency, not a pip requirement).

WINDOWS RUN ANALYSIS (AI)
run_app_ai.bat
or with on-the-fly model pull:
run_app_ai.bat --deepseek-r1:1.5b
dev mode (loads dev_ai.local.env endpoint + shows chat context messages):
run_app_ai.bat --dev

WINDOWS RUN VIEWER (AI)
run_viewer_ai.bat
or with on-the-fly model pull:
run_viewer_ai.bat --deepseek-r1:1.5b
dev mode (loads dev_ai.local.env endpoint + shows chat context messages):
run_viewer_ai.bat --dev

WINDOWS PRODUCTION RUN
cd frontend
npm run build
cd ..
.\backend\.venv\Scripts\python.exe launch.py

WINDOWS PRODUCTION RUN VIEWER
cd frontend
npm run build
cd ..
.\backend\.venv\Scripts\python.exe launch.py --viewer --port 8001

WINDOWS BUILD EXE TOOL ONLY (ONEFILE)
.\build_exe_windows.ps1 -Target Tool
output: .\dist\ProteomicsCoPYlot.exe

WINDOWS BUILD EXE VIEWER ONLY (ONEFILE)
.\build_exe_windows.ps1 -Target Viewer
output: .\dist\DataViewer.exe

WINDOWS BUILD NOTE
Tool and Viewer builds use different frontend modes.
Switching target requires a rebuild without -SkipFrontendBuild.

MACOS INSTALL
git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend
npm install
cd ..
chmod +x run_app_macos.sh run_viewer_macos.sh

MACOS RUN ANALYSIS
./run_app_macos.sh

MACOS RUN VIEWER
./run_viewer_macos.sh

MACOS AI PREREQUISITE
Install Ollama from https://ollama.com (external system dependency, not a pip requirement).

MACOS RUN ANALYSIS (AI)
./run_app_ai_macos.sh
or with on-the-fly model pull:
./run_app_ai_macos.sh --deepseek-r1:1.5b
dev mode:
./run_app_ai_macos.sh --dev

MACOS RUN VIEWER (AI)
./run_viewer_ai_macos.sh
or with on-the-fly model pull:
./run_viewer_ai_macos.sh --deepseek-r1:1.5b
dev mode:
./run_viewer_ai_macos.sh --dev

MACOS PRODUCTION RUN (ANALYSIS)
cd frontend
npm run build
cd ..
./backend/.venv/bin/python3 launch.py

MACOS PRODUCTION RUN (VIEWER)
cd frontend
npm run build
cd ..
./backend/.venv/bin/python3 launch.py --viewer --port 8001

MACOS BUILD APP TOOL ONLY (ONEFILE)
cd frontend
VITE_APP_MODE=analysis npm run build
cd ..
./backend/.venv/bin/python3 -m pip install --upgrade pip pyinstaller
./backend/.venv/bin/python3 -m PyInstaller --noconfirm --clean --onefile --name ProteomicsCoPYlot --paths backend --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all pandas --collect-all numpy --collect-all scipy --collect-all matplotlib --collect-all seaborn --collect-all plotly --collect-all pyarrow --collect-all openpyxl --add-data "frontend/dist:frontend_dist" --add-data "viewer_config.json:." --add-data "viewer_data:viewer_data" launch_tool.py
output: ./dist/ProteomicsCoPYlot

MACOS BUILD APP VIEWER ONLY (ONEFILE)
cd frontend
VITE_APP_MODE=viewer npm run build
cd ..
./backend/.venv/bin/python3 -m pip install --upgrade pip pyinstaller
./backend/.venv/bin/python3 -m PyInstaller --noconfirm --clean --onefile --name DataViewer --paths backend --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all pandas --collect-all numpy --collect-all scipy --collect-all matplotlib --collect-all seaborn --collect-all plotly --collect-all pyarrow --collect-all openpyxl --add-data "frontend/dist:frontend_dist" --add-data "viewer_config.json:." --add-data "viewer_data:viewer_data" launch_viewer.py
output: ./dist/DataViewer

LINUX INSTALL
git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend
npm install
cd ..
chmod +x run_app_linux.sh run_viewer_linux.sh

LINUX RUN ANALYSIS
./run_app_linux.sh

LINUX RUN VIEWER
./run_viewer_linux.sh

LINUX AI PREREQUISITE
Install Ollama from https://ollama.com (external system dependency, not a pip requirement).

LINUX RUN ANALYSIS (AI)
./run_app_ai_linux.sh
or with on-the-fly model pull:
./run_app_ai_linux.sh --deepseek-r1:1.5b
dev mode:
./run_app_ai_linux.sh --dev

LINUX RUN VIEWER (AI)
./run_viewer_ai_linux.sh
or with on-the-fly model pull:
./run_viewer_ai_linux.sh --deepseek-r1:1.5b
dev mode:
./run_viewer_ai_linux.sh --dev

LINUX PRODUCTION RUN (ANALYSIS)
cd frontend
npm run build
cd ..
./backend/.venv/bin/python3 launch.py

LINUX PRODUCTION RUN (VIEWER)
cd frontend
npm run build
cd ..
./backend/.venv/bin/python3 launch.py --viewer --port 8001

LINUX BUILD APP TOOL ONLY (ONEFILE)
cd frontend
VITE_APP_MODE=analysis npm run build
cd ..
./backend/.venv/bin/python3 -m pip install --upgrade pip pyinstaller
./backend/.venv/bin/python3 -m PyInstaller --noconfirm --clean --onefile --name ProteomicsCoPYlot --paths backend --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all pandas --collect-all numpy --collect-all scipy --collect-all matplotlib --collect-all seaborn --collect-all plotly --collect-all pyarrow --collect-all openpyxl --add-data "frontend/dist:frontend_dist" --add-data "viewer_config.json:." --add-data "viewer_data:viewer_data" launch_tool.py
output: ./dist/ProteomicsCoPYlot

LINUX BUILD APP VIEWER ONLY (ONEFILE)
cd frontend
VITE_APP_MODE=viewer npm run build
cd ..
./backend/.venv/bin/python3 -m pip install --upgrade pip pyinstaller
./backend/.venv/bin/python3 -m PyInstaller --noconfirm --clean --onefile --name DataViewer --paths backend --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all pandas --collect-all numpy --collect-all scipy --collect-all matplotlib --collect-all seaborn --collect-all plotly --collect-all pyarrow --collect-all openpyxl --add-data "frontend/dist:frontend_dist" --add-data "viewer_config.json:." --add-data "viewer_data:viewer_data" launch_viewer.py
output: ./dist/DataViewer

REMOTE OLLAMA HOSTING + TAILSCALE MANUAL
Goal: Run Ollama on PC-A (host) and use it from ProteomicsCoPYlot on PC-B (client) through your tailnet.

1) HOST PC (PC-A): INSTALL + TAILSCALE
- Install and sign in to Tailscale.
- Install Ollama from https://ollama.com

2) HOST PC (PC-A): EXPOSE OLLAMA ON TAILNET
Windows (PowerShell):
setx OLLAMA_HOST "0.0.0.0:11434"
Then fully restart Ollama (or reboot once).

Linux/macOS (terminal):
export OLLAMA_HOST=0.0.0.0:11434
ollama serve

3) HOST PC (PC-A): PULL A MODEL
Example:
ollama pull phi3:mini
Check:
ollama list

4) HOST PC (PC-A): FIREWALL CHECK (IF NEEDED)
Windows (PowerShell, admin):
New-NetFirewallRule -DisplayName "Ollama 11434" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11434

5) HOST PC (PC-A): FIND TAILSCALE ADDRESS
Use either:
- Tailscale IP (example: 100.x.y.z)
- MagicDNS hostname (if enabled)

6) CLIENT PC (PC-B): TEST CONNECTIVITY
PowerShell example:
Invoke-RestMethod -Method Get "http://<TAILSCALE_IP_OR_HOSTNAME>:11434/api/tags"
If you get JSON with models, connection works.

7) CLIENT PC (PC-B): CONNECT INSIDE ProteomicsCoPYlot
- Start AI app:
  run_app_ai.bat
  or
  run_viewer_ai.bat
- Open Chatbot -> AI Settings.
- Provider: Local (Ollama)
- Ollama endpoint:
  http://<TAILSCALE_IP_OR_HOSTNAME>:11434
- Press Enter (or leave the field) to apply endpoint.
- Select model and chat.

NOTES
- If endpoint is empty, the app uses local Ollama on the same machine.
- For remote endpoints, GPU status in the client UI is not available (GPU is managed on host PC-A).
- Model install/remove in the UI is sent to the selected endpoint.

TROUBLESHOOTING
- Timeout:
  Check Tailscale online status on both PCs and retry /api/tags test.
- No models shown:
  On host run "ollama list" and ensure at least one model is pulled.
- Connection refused:
  Verify OLLAMA_HOST is set to 0.0.0.0:11434 and Ollama was restarted.

DEV-ONLY LOCAL CONFIG FILE (NOT GITHUB)
- File: dev_ai.local.env (gitignored)
- Format:
  COPYLOT_DEV_OLLAMA_ENDPOINT=http://<TAILSCALE_IP_OR_HOSTNAME>:11434/api/tags
- This endpoint is auto-prefilled in chat only when starting with --dev.
- Context debug messages in chat are only shown in --dev mode.
