import re
from pathlib import Path


def test_kitten_installer_shell_and_embedded_python_are_syntactically_valid():
    installer = Path(__file__).resolve().parents[1] / "scripts" / "install_kitten_tts.sh"
    source = installer.read_text(encoding="utf-8")
    blocks = re.findall(r"python - <<'PY'\n(.*?)\nPY", source, flags=re.DOTALL)
    assert len(blocks) == 3
    for index, block in enumerate(blocks, start=1):
        compile(block, f"{installer}:python-block-{index}", "exec")
