"""
dump_advice.py - run the correlation advice through the PYTHON engine and write the answers to JSON.

The JavaScript side (tools/crosscheck.mjs) feeds the same inputs to advice.js and compares.  The
answers here are WORDS, not numbers, so this is the one part of the cross-check that compares text:
the rating of each correlation, the notes it carries, which one the app recommends, and the caption
shown under the box.  If a sentence is reworded on one side and not the other, this fails - which is
the point, because the page and the Streamlit app must say the same thing about the same well.

The Python takes the page's own input dictionary; the JavaScript takes a small object with the same
keys plus the survey already parsed into md/tvd lists (it has no survey parser in this path).  The
cases below carry both, and crosscheck.mjs picks the ones it needs.

Run from the docs/ folder:   python3 tools/dump_advice.py tools/advice_expected.json
"""
import json
import sys
import warnings

sys.path.insert(0, "..")
import app_helpers                                   # noqa: E402
from well import parse_survey_text, vertical_survey  # noqa: E402

warnings.simplefilter("ignore")

VERTICAL = "0 0\n8000 8000"
SLIGHT = "0 0\n4000 4000\n8000 7800"                 # about 11 degrees at worst: still "vertical"
DEVIATED = "0 0\n2000 2000\n6000 5500\n9000 7000"    # about 56 degrees at worst
HORIZONTAL = "0 0\n5000 5000\n7000 6000\n12000 6050" # a horizontal section

SURVEYS = {"vertical": VERTICAL, "slight": SLIGHT, "deviated": DEVIATED, "horizontal": HORIZONTAL}


def js_inputs(inputs):
    """The same case in the shape advice.js wants: the survey already parsed into md and tvd."""
    out = {"fluid_type": inputs.get("fluid_type", "oil"),
           "water_cut": inputs.get("water_cut", 0.0),
           "api": inputs.get("api", 35.0),
           "cgr": inputs.get("cgr", 0.0),
           "survey_mode": inputs.get("survey_mode", "vertical")}
    if out["survey_mode"] == "vertical":
        md, tvd = vertical_survey(inputs.get("depth", 8000.0))
    else:
        md, tvd = parse_survey_text(inputs["survey_text"])
    out["md"], out["tvd"] = md, tvd
    return out


def cases():
    out = []
    for shape, text in SURVEYS.items():
        survey = {"survey_mode": "vertical"} if shape == "vertical" else \
                 {"survey_mode": "deviated", "survey_text": text}
        # ---- oil: water cut and oil gravity are what move the ratings ----
        for wc in (0.0, 0.05, 0.10, 0.11, 0.30, 0.90):
            for api in (12.0, 19.9, 20.0, 35.0, 48.0):
                inputs = {"fluid_type": "oil", "water_cut": wc, "api": api, **survey}
                out.append((f"advice_oil_{shape}", "correlation_advice", inputs))
                out.append((f"recommend_oil_{shape}", "recommend_correlation", inputs))
                # only the correlations this fluid type offers: there is no Gray for an oil well
                for key in app_helpers.correlation_advice(inputs):
                    out.append((f"caption_oil_{shape}", "correlation_caption", inputs, key))
        # ---- gas: the condensate ratio is what moves the ratings ----
        for cgr in (0.0, 1.0, 25.0, 50.0, 51.0, 200.0):
            inputs = {"fluid_type": "gas", "cgr": cgr, **survey}
            out.append((f"advice_gas_{shape}", "correlation_advice", inputs))
            out.append((f"recommend_gas_{shape}", "recommend_correlation", inputs))
            for key in app_helpers.correlation_advice(inputs):
                out.append((f"caption_gas_{shape}", "correlation_caption", inputs, key))
        out.append((f"inclination_{shape}", "max_inclination_deg", {**survey}))
    return out


def run_one(func_name, inputs, key=None):
    if func_name == "max_inclination_deg":
        return app_helpers.max_inclination_deg(inputs)
    if func_name == "correlation_advice":
        return app_helpers.correlation_advice(inputs)
    if func_name == "recommend_correlation":
        best, notes = app_helpers.recommend_correlation(inputs)
        return {"key": best, "notes": notes}
    if func_name == "correlation_caption":
        # the Streamlit caption is markdown, with the name in bold; the page writes the name in the
        # heading instead, so the stars are not part of what is compared
        return app_helpers.correlation_caption(inputs, key).replace("**", "").replace("*", "")
    raise ValueError(func_name)


def main(path):
    rows = []
    for case in cases():
        name, func_name, inputs = case[0], case[1], case[2]
        key = case[3] if len(case) > 3 else None
        args = [js_inputs(inputs)] if func_name != "max_inclination_deg" else [js_inputs(inputs)]
        if key is not None:
            args.append(key)
        rows.append({"name": name, "func": func_name, "args": args,
                     "want": run_one(func_name, inputs, key)})
    with open(path, "w") as handle:
        json.dump(rows, handle)
    print(f"{len(rows)} cases written to {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tools/advice_expected.json")
