import os
import re
import io
import time
import zipfile
import requests
import argparse
import configparser
import urllib.request

import numpy as np
import PIL.Image as Image

from pero_ocr.document_ocr.page_parser import PageParser
from pero_ocr.document_ocr.layout import PageLayout, create_ocr_processing_element


def get_args():
    """
    method for parsing of arguments
    """
    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--config", action="store", dest="config", help="Config path.")
    parser.add_argument("-a", "--api-key", action="store", dest="api", help="API key.")
    parser.add_argument("-e", "--preferred-engine", action="store", dest="engine", help="Preferred engine ID.")

    args = parser.parse_args()

    return args


def join_url(*paths):
    final_paths = []
    first_path = paths[0].strip()
    if first_path[-1] == '/':
        first_path = first_path[:-1]
    final_paths.append(first_path)
    for path in paths[1:]:
        final_paths.append(path.strip().strip('/'))
    return '/'.join(final_paths)


def get_engine(config, headers, engine_id):
    r = requests.get(join_url(config['SERVER']['base_url'],
                              config['SERVER']['get_download_engine'],
                              str(engine_id)),
                     headers=headers)

    d = r.headers['content-disposition']
    filename = re.findall("filename=(.+)", d)[0]
    engine_name = filename[:-4].split('#')[0]
    engine_version = filename[:-4].split('#')[1]
    if not os.path.exists(os.path.join(config["SETTINGS"]['engines_path'], filename[:-4])):
        os.mkdir(os.path.join(config["SETTINGS"]['engines_path'], filename[:-4]))
        with open(os.path.join(config["SETTINGS"]['engines_path'], filename[:-4], filename), 'wb') as f:
            f.write(r.content)
        with zipfile.ZipFile(os.path.join(config["SETTINGS"]['engines_path'], filename[:-4], filename), 'r') as f:
            f.extractall(os.path.join(config["SETTINGS"]['engines_path'], filename[:-4]))

    engine_config = configparser.ConfigParser()
    engine_config.read(os.path.join(config["SETTINGS"]['engines_path'], filename[:-4], 'config.ini'))
    page_parser = PageParser(engine_config,
                             config_path=os.path.dirname(os.path.join(config["SETTINGS"]['engines_path'],
                                                                      filename[:-4],
                                                                      'config.ini')))
    return page_parser, engine_name, engine_version


def get_page_layout_text(page_layout):
    text = ""
    for line in page_layout.lines_iterator():
        text += "{}\n".format(line.transcription)
    return text


def main():
    args = get_args()

    config = configparser.ConfigParser()
    if args.config is not None:
        config.read(args.config)
    else:
        config.read('config.ini')

    if args.api is not None:
        config["SETTINGS"]['api_key'] = args.api

    if args.engine is not None:
        config["SETTINGS"]['preferred_engine'] = args.preferred_engine

    with requests.Session() as session:
        headers = {'api-key': config['SETTINGS']['api_key']}
        page_parser, engine_name, engine_version = get_engine(config, headers, config["SETTINGS"]['preferred_engine'])

        while True:
            r = session.get(join_url(config['SERVER']['base_url'],
                                     config['SERVER']['get_processing_request'],
                                     config['SETTINGS']['preferred_engine']),
                            headers=headers)
            request = r.json()
            status = request['status']
            page_id = request['page_id']
            page_url = request['page_url']
            engine_id = request['engine_id']

            if status == 'success':
                if engine_id != int(config['SETTINGS']['preferred_engine']):
                    page_parser, engine_name, engine_version = get_engine(config, headers, engine_id)
                    config['SETTINGS']['preferred_engine'] = str(engine_id)

                page = urllib.request.urlopen(page_url).read()
                stream = io.BytesIO(page)
                pil_image = Image.open(stream)

                open_cv_image = np.array(pil_image)
                open_cv_image = open_cv_image[:, :, ::-1].copy()

                page_layout = PageLayout(id=page_id, page_size=(pil_image.size[1], pil_image.size[0]))
                page_layout = page_parser.process_page(open_cv_image, page_layout)

                headers = {'api-key': config['SETTINGS']['api_key'],
                           'engine-version': engine_version,
                           'score': '100'}

                ocr_processing = create_ocr_processing_element(id="IdOcr",
                                                               software_creator_str="Project PERO",
                                                               software_name_str="{}" .format(engine_name),
                                                               software_version_str="{}" .format(engine_version),
                                                               processing_datetime=None)

                session.post(join_url(config['SERVER']['base_url'], config['SERVER']['post_upload_results'], page_id),
                             files={'alto': ('{}_alto.xml' .format(page_id), page_layout.to_altoxml_string(ocr_processing=ocr_processing), 'text/plain'),
                                    'xml': ('{}.xml' .format(page_id), page_layout.to_pagexml_string(), 'text/plain'),
                                    'txt': ('{}.txt' .format(page_id), get_page_layout_text(page_layout), 'text/plain')},
                             headers=headers)
            else:
                time.sleep(10)


if __name__ == '__main__':
    main()