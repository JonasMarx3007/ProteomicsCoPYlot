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

WINDOWS RUN VIEWER (AI)
run_viewer_ai.bat
or with on-the-fly model pull:
run_viewer_ai.bat --deepseek-r1:1.5b

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

MACOS RUN VIEWER (AI)
./run_viewer_ai_macos.sh
or with on-the-fly model pull:
./run_viewer_ai_macos.sh --deepseek-r1:1.5b

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

LINUX RUN VIEWER (AI)
./run_viewer_ai_linux.sh
or with on-the-fly model pull:
./run_viewer_ai_linux.sh --deepseek-r1:1.5b

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
