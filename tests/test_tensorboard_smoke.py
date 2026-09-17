from pathlib import Path

from torch.utils.tensorboard import SummaryWriter


def test_tensorboard_smoke_logging(tmp_path):
    log_dir = tmp_path / "runs" / "smoke"
    writer = SummaryWriter(log_dir=str(log_dir))
    writer.add_scalar("smoke/loss", 0.5, 0)
    writer.add_scalar("smoke/loss", 0.4, 1)
    writer.flush()
    writer.close()
    files = list(log_dir.glob("events.out.tfevents.*"))
    assert files, "TensorBoard should have written an event file."
