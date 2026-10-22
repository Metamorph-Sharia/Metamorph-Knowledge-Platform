"""The step 9 SageMaker training job's entry point: step9.sh with SageMaker's folders.

    inputs channel    /opt/ml/input/data/inputs    the files stage-upload.sh made, from S3
    checkpoints       /opt/ml/checkpoints          MinerU's readings, a folder per connector, and logs/: synced to
                                                   S3 while the job runs (so its progress can be followed there), and
                                                   restored into a new job given the same folder, which resumes
    model directory   /opt/ml/model                the results: SageMaker uploads them as model.tar.gz at the end

RUN_ID and MODE come from the job's environment variables (defaults step9 and run).
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

environment = os.environ | {
    "INPUTS": os.environ.get("SM_CHANNEL_INPUTS", "/opt/ml/input/data/inputs"),
    "WORK": "/opt/ml/output/work",  # on the job's storage volume; only /opt/ml/output/data would be uploaded
    "CACHE": "/opt/ml/checkpoints",
    "LOGS": "/opt/ml/checkpoints/logs",
    "OUT": os.environ.get("SM_MODEL_DIR", "/opt/ml/model"),
    "HOME": os.environ.get("HOME") or "/root",
}
sys.exit(subprocess.call(["bash", str(HERE / "step9.sh")], env=environment))
