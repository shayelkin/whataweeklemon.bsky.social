#!/usr/bin/env python3

from collections import namedtuple
import datetime
import io
import json
import logging
import os
import tempfile
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
import pytz
import requests

ATP_PDS_HOST = "https://bsky.social"

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

### Mostly copied from create_bsky_post.py because I can't be bothered.

def bsky_login_session(pds_url: str, handle: str, password: str) -> Dict:
    resp = requests.post(
        pds_url + "/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
    )
    resp.raise_for_status()
    return resp.json()

def upload_file(pds_url, access_token, mimetype, img_bytes) -> Dict:
    resp = requests.post(
        pds_url + "/xrpc/com.atproto.repo.uploadBlob",
        headers={
            "Content-Type": mimetype,
            "Authorization": "Bearer " + access_token,
        },
        data=img_bytes,
    )
    resp.raise_for_status()
    return resp.json()["blob"]

def upload_images(pds_url: str, access_token: str, fd: io.IOBase , alt_text: str) -> Dict[str, str]:
    fd.seek(0)
    img_bytes = fd.read()
    # this size limit specified in the app.bsky.embed.images lexicon
    assert len(img_bytes) <= 1000000

    blob = upload_file(pds_url, access_token, "image/jpeg", img_bytes)

    return {
        "$type": "app.bsky.embed.images",
        "images": [{"alt": alt_text, "image": blob}],
    }

def create_post(pds_url: str, handle: str, password: str, image_file: io.IOBase, alt_text: str, dry_run: bool = False):
    session = bsky_login_session(pds_url, handle, password)
    # trailing "Z" is preferred over "+00:00"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    # these are the required fields which every post must include
    post = {
        "$type": "app.bsky.feed.post",
        "text": "",
        "createdAt": now,
    }

    post["embed"] = upload_images(pds_url, session["accessJwt"], image_file, alt_text)

    logger.info("Creating post: %s", json.dumps(post, indent=None))

    if not dry_run:
        resp = requests.post(
            pds_url + "/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": "Bearer " + session["accessJwt"]},
            json={
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": post,
            },
        )

        logger.info("createRecord response: %s", json.dumps(resp.json(), indent=None))
        resp.raise_for_status()

#### End create_bsky_post.py

def day(zone: Optional[str] = "US/Pacific") -> str:
    tz = pytz.timezone(zone)
    return datetime.datetime.now(tz).strftime("%A")

MemeTemplate = namedtuple("MemeTemplate", ["image_file", "font_file", "font_size", "top", "left", "min_width", "color", "bg_color"])

def create_image(template: MemeTemplate, text: str) -> io.IOBase:
    image = Image.open(template.image_file)
    draw = ImageDraw.Draw(image)

    font = ImageFont.truetype(font=template.font_file, size=template.font_size)

    _, _, text_width, text_height = font.getbbox(text)
    text_width = max(text_width, template.min_width)
    draw.rectangle((template.top, template.left, template.top+text_width, template.left+text_height), fill=template.bg_color)
    draw.text((template.top, template.left), text, font=font, fill=template.color, background=template.bg_color)

    tf = tempfile.TemporaryFile()
    image.save(fp=tf, format="jpeg")
    logger.info("Wrote image: %d bytes", tf.tell())

    return tf

def deserialize_color(color: str) -> tuple:
    res = tuple(int(c.strip()) for c in color.split(',', maxsplit=2))
    assert len(res) == 3
    return res

def deserialize_meme_template(template: dict, base_path: Optional[str] = "./") -> MemeTemplate:
    return MemeTemplate(
        image_file=os.path.join(base_path, template["image_file"]),
        font_file=os.path.join(base_path, template["font_file"]),
        font_size=template["font_size"],
        top=template["top"],
        left=template["left"],
        min_width=template["min_width"],
        color=deserialize_color(template["color"]),
        bg_color=deserialize_color(template["bg_color"]),
    )

def create_meme_image(template_fname: str, text: str) -> io.IOBase:
    base_path = os.path.dirname(template_fname)

    with open(template_fname) as f:
        template = deserialize_meme_template(json.load(f), base_path=base_path)
        return create_image(template, text)

def get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise Exception(f"{name} not set")
    return val

def main(config_fname):
    day_name = day()
    image = create_meme_image("data/template.json", day_name)
    alt_text = "Liz Lemon (Tina Fey), complains to character Jack Donaghy (Alec Baldwin), " \
        + "about having finished a hard week of work, with Donaghey reminding her that it is " \
        + "still " + day_name
    
    with open(config_fname, "r") as config_f:
        config = json.load(config_f)
        create_post(ATP_PDS_HOST,
                    config["handle"],
                    config["password"],
                    image,
                    alt_text,
                    config["dry_run"])


if __name__ == '__main__':
    main(".config.json")
