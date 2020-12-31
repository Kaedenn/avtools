# avtools

Collection of stand-alone programs for managing media

| Tool | Description |
|------|-------------|
| `avinfo.py` | Extract information about audio or video files |
| `avmontage.py` | Create a collage of equally-spaced frames from a video file |
| `imagemanage.py` | Mechanism for selecting images for modification |

# avinfo.py - Extract information from a media file

`avinfo.py` will invoke (by default) `ffprobe`, interpret the results, and display the information using one of the supported formats.

## Command-line arguments

Usage:
```
avinfo.py [-h]
          [-e EXE | --exe EXE]
          [-l LEVEL | --log-level LEVEL]
          [-I ARGS | --iargs ARGS]
          [-O ARGS | --oargs ARGS]
          [-s STREAMS | --streams STREAMS]
          [-C | --no-color]
          [--raw-data]
          [-f FORMAT | --format FORMAT
            | -J | --json
            | -P | --py
            | -K | --kv
            | -S | --sum]
          [-q,--quiet] [-i,--info] [-v,--verbose] [-d,--debug]
          path [path ...]
```

Permissible values for `-l,--log-level` are `quiet`, `panic`, `fatal`, `error`, `warning`, `info`, `verbose`, and `debug`.

The arguments `-I,--iargs` and `-O,--oargs` are used to pass extra arguments to the executable specified via `-e,--exe`. These arguments can be specified as many times as needed.

Permissible values for `-f,--format` are `json`, `json-pretty`, `python`, `kv`, and `summary`. `-J,--json` implies `-f json-pretty`, `-P,--py` implies `-f python`, `-K,--kv` implies `-f kv`, and `-S,--sum` implies `-f summary`. All of these arguments are mutually-exclusive.

## Formatting

| Format Argument | Shorthand | Description |
|-----------------|-----------|-------------|
| `json`         | Default | JSON output, condensed onto a single line |
| `json-pretty`  | `-J`, `--json` | JSON output with indentation and sorted keys |
| `python`       | `-P`, `--py` | Python literal output (not generally useful) |
| `kv`           | `-K`, `--kv` | `<key>=<value>` formatted output (explained below) |
| `summary`      | `-S`, `--sum` | Brief summary of the media as text |

### JSON output format

This format outputs a monolithic block of JSON text (indented and sorted if using `json-pretty`) with approximately the following structure:

```json
{
  "format": {
    "filename": <path as specified by probe command>,
    "name": <name of the file>,
    "path": <absolute path to the file>,
    "format_long_name": <name of the file format>,
    "format_name": <short name of the file format>,
    "duration": <number>,
    "bit_rate": <number>,
    "nb_frames": <number>
    "start_time": <number>,
    "nb_streams": <total number of streams present>,
    "size": <filesize in bytes>,

    ... any other values given by the probe command ...
  },
  "audio_streams": [{
    TODO
  }, ...],
  "video_streams": [{
    TODO
  }, ...],
  "other_streams": [{ ... }, ...]
}
```

`audio_streams`, `video_streams`, and `other_streams` are all lists of objects. The `json["format"]["nb_streams"]` value holds the total number of streams.

`other_streams` will include subtitle streams, if present, along with any other streams not marked as audio or video.

### Key-value output format

TODO

### Summary output format

TODO

## Caution about `--raw-data`

Note that passing `--raw-data` will result in the values for duration, start time, number of frames, etc. remaining as strings, instead of being converted to floating-point. If a downstream script expects the duration, for example, to be a numeric value, then haphazardly passing `--raw-data` can break these downstream scripts.

This argument is given for the rare cases when the direct output of `ffprobe` or `avprobe` is desired.

## Underlying executable and command-line arguments

By default, `avinfo.py` uses `ffprobe`. This can be changed by specifying an alternate program via `-e,--exe`. For example, to use a system-installed `avprobe`, one can use `-e avprobe`.

The probe command has the following structure:
```shell-script
  $(PROBE)            # Value of -e,--exe
    -show_format -show_streams -of json
    -v $(LOGLEVEL)    # Specified via -l,--log-level
    $(INPUT_ARGS)     # Specified via -I,--iargs
    $(PATH)
    $(OUTPUT_ARGS)    # Specified via -O,--oargs
```

## Extraneous details

`avinfo.py` is intended for use as part of a larger tool-chain and has limited use by itself.

# avmontage.py - Collage equally-spaced frames from a video into a single image

TODO: Description

## Command-line arguments

TODO

# imagemanage.py - Display images in a way that simplifies file management

TODO: Description

## Command-line arguments

TODO

