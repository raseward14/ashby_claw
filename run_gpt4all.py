from gpt4all import GPT4All
from pathlib import Path
import sys

MODEL_DIRS = [Path("models"), Path.home() / ".cache" / "gpt4all", Path.home() / ".gpt4all"]


def find_local_model() -> str | None:
	for d in MODEL_DIRS:
		if not d.exists():
			continue
		for pattern in ("**/*.gguf", "**/*ggml*.bin", "**/*.bin", "**/*.bin.gz", "**/*ggml*"):
			for p in d.glob(pattern):
				if p.is_file() and p.stat().st_size > 0:
					return str(p)
	return None


def main() -> None:
	model_path = find_local_model()
	if model_path:
		print(f"Using local model: {model_path}")
		gpt = GPT4All(model_name=Path(model_path).name, model_path=Path(model_path).parent, allow_download=False)
	else:
		print("No local model binary found in the usual locations:")
		for d in MODEL_DIRS:
			print(f"  - {d}")
		print("\nPlace a GGML model file (eg. ggml-model.bin) in `models/` or ~/.cache/gpt4all/ and re-run.")
		print("If you'd like, I can download a model for you; grant permission and tell me which model.")
		sys.exit(2)

	prompt = "List 3 ways to add a tag to a candidate in an ATS."
	resp = gpt.generate(prompt)
	print(resp)


if __name__ == "__main__":
	main()