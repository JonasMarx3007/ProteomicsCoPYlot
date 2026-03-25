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
