"""Windows launcher for the Streamlit app.

The default asyncio loop on Windows prints a ConnectionResetError (WinError
10054) when the browser drops a websocket. It is harmless, but it clutters the
terminal during a demo. The selector loop does not do it.

    python run.py
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from streamlit.web import cli as stcli  # noqa: E402

if __name__ == "__main__":
    sys.argv = ["streamlit", "run", "app_streamlit.py", "--server.headless", "false"]
    sys.exit(stcli.main())
