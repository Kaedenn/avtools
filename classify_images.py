#!/usr/bin/env python3

"""
Classify images across a list of words
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import textwrap

import torch
from PIL import Image
import open_clip

logging.basicConfig(format="%(module)s:%(lineno)s: %(levelname)s: %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".bmp",
  ".webp",
  ".tif",
  ".tiff",
}

def describe_openclip_model(model: str, pretrained: str) -> str:
  name = f"{model} {pretrained}".lower()
  if "mobileclip" in name:
    return "Fast/mobile-friendly; use when speed matters more than accuracy."
  if "siglip" in name:
    return "Modern strong model family; good candidate for zero-shot classification."
  if "dfn5b" in name or "dfn2b" in name:
    return "High-quality filtered-data model; good accuracy candidate if hardware allows."
  if "datacomp_xl" in name or "datacomp_l" in name:
    return "Strong general-purpose model; good default choice."
  if "openai" in name:
    return "Stable baseline/reference CLIP model; good for comparison."
  if "laion2b" in name:
    return "Large LAION-trained model; broad general coverage."
  if "laion400m" in name:
    return "Older/smaller LAION model; usable but usually not first choice."
  if "coca" in name:
    return "Captioning-oriented CLIP variant; not my first pick for pure classification."
  if "xlm" in name or "nllb" in name or "i18n" in name:
    return "Multilingual text encoder; useful if prompts are not only English."
  if "rn50" in name or "rn101" in name:
    return "Older ResNet CLIP architecture; mostly useful as a lightweight/baseline model."
  if "vit-b" in name:
    return "Smaller ViT; faster, lower VRAM, usually lower accuracy."
  if "vit-l" in name:
    return "Larger ViT; better quality, slower."
  if "vit-h" in name or "vit-g" in name or "bigg" in name:
    return "Very large model; try only with enough VRAM/compute."
  if "eva01" in name or "eva02" in name:
    return (
        "EVA-CLIP family; strong zero-shot classification candidate. "
        "Usually worth benchmarking if hardware allows."
    )
  if "vitamin" in name:
    if "xl" in name or "l2" in name:
      return (
        "ViTamin large-family model; strong but likely VRAM-heavy. "
        "Benchmark for accuracy if speed is acceptable."
      )
    if "-l" in name:
      return (
        "ViTamin-L model; strong accuracy-oriented candidate, often better "
        "than plain ViT-L at similar scale."
      )
    if "-b" in name:
      return (
        "ViTamin-B model; balanced speed/accuracy candidate."
      )
    if "-s" in name:
      return (
        "ViTamin-S model; smaller/faster candidate."
      )
  if "ltt" in name:
    return (
      "Long-text-trained variant; potentially useful for richer prompts, "
      "but benchmark against the non-LTT version."
    )
  if "convnext" in name:
    if "xxlarge" in name:
      return "Very large ConvNeXt CLIP; accuracy-oriented, heavy."
    if "large" in name:
      return "Large ConvNeXt CLIP; strong convolutional alternative to ViT-L/H."
    if "base" in name:
      return "Base ConvNeXt CLIP; convolutional alternative with moderate compute."
  return "No specific note available; benchmark on your own labeled sample."

def is_image(path: str) -> bool:
  """Return True if path looks like a supported image file."""
  return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS

def gather_images(
  paths: list[str],
  from_file: str | None = None,
  skip_missing: bool = False,
  recurse: bool = False,
) -> list[str]:
  """Gather all of the images we need to operate on."""
  results: list[str] = []

  def add_path(path: str) -> None:
    """Add a path entry """
    if os.path.isfile(path):
      # Explicit file paths are trusted as images.
      results.append(path)
    elif os.path.isdir(path):
      if recurse:
        for root, _, filenames in os.walk(path):
          for filename in filenames:
            full_path = os.path.join(root, filename)
            if is_image(full_path):
              results.append(full_path)
      else:
        with os.scandir(path) as entries:
          for entry in entries:
            if entry.is_file() and is_image(entry.path):
              results.append(entry.path)
    elif not skip_missing:
      if not os.path.exists(path):
        raise FileNotFoundError(path)
      raise ValueError(f"Not a file or directory: {path}")

  for path in paths:
    add_path(path)

  if from_file is not None:
    with open(from_file, "r", encoding="utf-8") as f:
      for line in f:
        path = line.strip()
        if not path or path.startswith("#"):
          continue
        add_path(path)

  return results

MODEL_CANDIDATES = [
    ("ViT-L-14", "datacomp_xl_s13b_b90k"),
    ("ViT-H-14-378", "dfn5b"),
    ("ViT-B-16", "datacomp_l_s1b_b8k"),
    ("ViT-B-32", "openai"),
    ("ViT-L-14", "openai"),
]

DEFAULT_LABELS = [
    "a photograph of a black animal sitting down",
    "a photograph of a cat with visible drooling",
    "a close-up photograph of a cat with visible injury or disease",
    "a photograph of a cat with severe facial injury",
    "a photograph of a healthy house cat",
    "a photograph of a healthy black cat",
    "a photograph of a pet cat sitting on a cat tree",
    "a photograph without any animal",
    "a landscape photograph",
    "a photograph of an empty room",
    "a photograph of a person",
    "a photograph of a car",
]

DEFAULT_MODEL = ("ViT-L-14", "datacomp_xl_s13b_b90k")

def main():
  ap = argparse.ArgumentParser(epilog=textwrap.dedent(f"""
  This program will classify images according to a sequence of words or phrases.

  Default model:
    "{' '.join(DEFAULT_MODEL)}" {describe_openclip_model(*DEFAULT_MODEL)}

  Note that the -M,--model argument takes two values: the model and dataset.
  Run `%(prog)s --list` to see all of the available pre-trained models. Both
  values must be given to -M,--model.

  Use -c,--classify to limit output only to the most accurate match. Without
  -c,--classify, the output includes the results of all matches.
  """), formatter_class=argparse.RawDescriptionHelpFormatter)
  ag = ap.add_argument_group("Image Selection")
  ag.add_argument("path", nargs="*", help="paths to files or directories")
  ag.add_argument("-f", "--from-file", metavar="FILE",
      help="read images from %(metavar)s, one per line")
  ag.add_argument("--skip-missing", action="store_true",
      help="skip missing entries instead of issuing an error")
  ag.add_argument("-r", "--recurse", action="store_true",
      help="recurse into subdirectories")

  ag = ap.add_argument_group("Phrase List")
  ag.add_argument("-w", "--word-list", metavar="FILE",
      help="read classification phrases from %(metavar)s")
  ag.add_argument("-W", "--word", metavar="WORD", action="append",
      help="add a specific classification phrase")

  ag = ap.add_argument_group("AI Configuration")
  ag.add_argument("-M", "--model", nargs=2, metavar="STR",
      default=DEFAULT_MODEL,
      help="pick which pretrained AI model to use (default: %(default)s)")
  ag.add_argument("--raw-logits", action="store_true",
      help="do not normalize text probabilities to [0,1]")
  ag.add_argument("-c", "--classify", action="store_true",
      help="report only the single most likely phrase")
  ag.add_argument("--list", action="store_true",
      help="list available pretrained AI models and exit")

  ag = ap.add_argument_group("Output Configuration")
  ag.add_argument("-o", "--output", type=argparse.FileType("wt"),
      metavar="FILE", default=sys.stdout,
      help="write to %(metavar)s (default: stdout)")
  ag.add_argument("--json", action="store_true",
      help="output as JSON (default: CSV)")
  ag.add_argument("--indent", action="store_true",
      help="properly indent JSON output")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-B", "--basename", action="store_true",
      help="strip directory components from image paths")
  mg.add_argument("-A", "--abspath", action="store_true",
      help="normalize paths to be absolute")
  mg.add_argument("-R", "--relpath", action="store_true",
      help="normalize paths to be relative")

  ag = ap.add_argument_group("Logging")
  ag.add_argument("-v", "--verbose", action="store_true",
      help="enable verbose output")

  args = ap.parse_args()
  if args.verbose:
    logger.setLevel(logging.DEBUG)

  if args.list:
    print("The following models are available:")
    print("MODEL_NAME DATASET_NAME - DESCRIPTION")
    model_info = {}
    for model_name, dataset in open_clip.list_pretrained():
      if model_name not in model_info:
        model_info[model_name] = []
      model_info[model_name].append(dataset)
    for model_name, datasets in sorted(model_info.items()):
      for dataset in sorted(datasets):
        model_desc = describe_openclip_model(model_name, dataset)
        print(f"{model_name} {dataset} - {model_desc}")
    print("\nDefault model and dataset:")
    print(*DEFAULT_MODEL, "-", describe_openclip_model(*DEFAULT_MODEL))
    raise SystemExit(0)

  words = []
  if args.word_list:
    with open(args.word_list, "rt", encoding="UTF-8") as fobj:
      words = fobj.read().splitlines()
  if args.word:
    for word in args.word:
      if word not in words:
        words.append(word)
  if not words:
    logger.error("No classification phrases provided")
    logger.error("Use either -w FILE or -W WORD to provide phrases")
    raise SystemExit(1)

  phrases = open_clip.tokenize(words)

  images = gather_images(
      args.path,
      args.from_file,
      args.skip_missing,
      args.recurse
  )
  if not images:
    logger.info("Nothing to do")
    raise SystemExit(0)

  num_words = len(words)
  num_images = len(images)

  logger.debug("Classifying %d images across %d words", num_images, num_words)

  def normalize_path(path):
    "Transform the path based on which arguments were passed"
    if args.basename:
      return os.path.basename(path)
    if args.abspath:
      return os.path.realpath(path)
    if args.relpath:
      return os.path.relpath(path)
    return path

  logger.debug("Loading model %s dataset %s", *args.model)
  model_name, pretrained_name = args.model
  model, _, preprocess = open_clip.create_model_and_transforms(
      model_name, pretrained=pretrained_name)

  label_probs: dict[str, tuple[str, float]] = {}
  for idx, path in enumerate(images):
    logger.info("Image %d/%d: %s", idx+1, num_images, path)
    image = preprocess(Image.open(path)).unsqueeze(0)
    with torch.no_grad():
      image_features = model.encode_image(image)
      text_features = model.encode_text(phrases)
      if not args.raw_logits:
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
      text_probs = (image_features @ text_features.T)[0]
      text_probs = 100.0 * (text_probs + 1.0) / 2.0
      image_path = normalize_path(path)
      label_probs[image_path] = list(zip(words, [prob.item() for prob in text_probs]))
      for phrase, prob in label_probs[image_path]:
        logger.debug("%g match for %r against %r", prob, path, phrase)

  if args.json:
    dump_args = {"sort_keys": True}
    if args.indent:
      dump_args["indent"] = 2
    results = {}
    for path, labels in label_probs.items():
      best_match = max(labels, key=lambda word_prob: word_prob[1])
      results[path] = {
        "Best Match": best_match[0],
        "Confidence": best_match[1],
      }
      if not args.classify:
        results["path"].update(**dict(labels))
    json.dump(results, args.output, **dump_args)
  else:
    header = ["File Path", "Best Match", "Confidence"] + words
    csvw = csv.DictWriter(args.output, fieldnames=header)
    csvw.writeheader()
    for path, labels in label_probs.items():
      best_match = max(labels, key=lambda word_prob: word_prob[1])
      row = {
        "File Path": path,
        "Best Match": best_match[0],
        "Confidence": best_match[1]
      }
      if not args.classify:
        row.update(**dict(labels))
      csvw.writerow(row)

if __name__ == "__main__":
  main()

# vim: set ts=2 sts=2 sw=2:
