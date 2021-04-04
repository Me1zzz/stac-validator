import json
import os
from json.decoder import JSONDecodeError
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import click
import jsonschema
import pystac
import requests
from jsonschema import RefResolver
from pystac.serialization import identify_stac_object
from requests import exceptions


class StacValidate:
    def __init__(
        self,
        stac_file: str = None,
        recursive: bool = False,
        core: bool = False,
        extensions: bool = False,
        custom: str = "",
        homegrown: bool = False,
    ):
        self.stac_file = stac_file
        self.message = []
        self.custom = custom
        self.homegrown = homegrown

    def print_file_name(self):
        if self.stac_file:
            click.echo(click.format_filename(self.stac_file))

    def get_stac_type(self, stac_content: dict) -> str:
        try:
            stac_object = identify_stac_object(stac_content)
            return stac_object.object_type
        except TypeError as e:
            print("TypeError: " + str(e))
            return ""

    @staticmethod
    def create_err_msg(err_type: str, err_msg: str) -> dict:
        return {"valid stac": False, "error type": err_type, "error message": err_msg}

    @staticmethod
    def is_valid_url(url: str) -> bool:
        result = urlparse(url)
        if result.scheme in ("http", "https"):
            return True
        else:
            return False

    def get_stac_version(self, stac_content: dict) -> str:
        return stac_content["stac_version"]

    def fetch_and_parse_file(self, input_path: str):
        data = None
        # try:
        if self.is_valid_url(input_path):
            resp = requests.get(input_path)
            data = resp.json()
        else:
            with open(input_path) as f:
                data = json.load(f)

        return data

    def recursive(self, stac_content):
        val = pystac.validation.validate_all(
            stac_dict=stac_content, href=self.stac_file
        )
        print(val)

    def core(self, stac_content, stac_type, version):
        stacschema = pystac.validation.JsonSchemaSTACValidator()
        version = self.get_stac_version(stac_content)
        val = stacschema.validate_core(
            stac_dict=stac_content,
            stac_object_type=stac_type,
            stac_version=version,
        )
        print(val)

    def extensions(self, stac_content):
        self.print_file_name()
        val = pystac.validation.validate_dict(
            stac_dict=stac_content, href=self.stac_file
        )
        print(val)

    def custom_val(self, stac_content):
        # in case the path to custom json schema is local
        # it may contain relative references
        schema = self.fetch_and_parse_file(self.custom)
        if os.path.exists(self.custom):
            custom_abspath = os.path.abspath(self.custom)
            custom_dir = os.path.dirname(custom_abspath).replace("\\", "/")
            custom_uri = f"file:///{custom_dir}/"
            resolver = RefResolver(custom_uri, self.custom)
            jsonschema.validate(stac_content, schema, resolver=resolver)
        else:
            jsonschema.validate(stac_content, schema)

    def homegrown_val(self, version, stac_content, stac_type):
        print(version)
        if version == "0.9.0":
            self.custom = "https://cdn.staclint.com/v0.9.0/collection.json"
            self.custom_val(stac_content)

    def run(cls):
        # stac_val = StacValidate(stac_file)
        message = {"path": cls.stac_file}
        # cls.message["path"] = cls.stac_file
        valid = False
        try:
            stac_content = cls.fetch_and_parse_file(cls.stac_file)
            stac_type = cls.get_stac_type(stac_content).upper()
            version = cls.get_stac_version(stac_content)
            message["asset type"] = stac_type
            message["version"] = version

            if cls.homegrown is True:
                message["validation method"] = "homegrown"
                cls.homegrown_val(version, stac_content, stac_type)
            if cls.recursive is True:
                message["validation method"] = "recursive"
                if stac_type == "ITEM":
                    message["error message"] = "Can not recursively validate an ITEM"
                else:
                    cls.recursive(stac_content)
                    valid = True
            if cls.core is True:
                cls.message["validation method"] = "core"
                cls.core(stac_content, stac_type, version)
                valid = True
            if cls.extensions is True:
                cls.message["validation method"] = "extensions"
                cls.extensions(stac_content)
                valid = True
            if cls.custom != "":
                message["validation method"] = "custom"
                message["schema"] = cls.custom
                # schema = cls.fetch_and_parse_file(cls.custom)
                cls.custom_val(stac_content)
                valid = True

        except pystac.validation.STACValidationError as e:
            message.update(cls.create_err_msg("STACValidationError", str(e)))
        except ValueError as e:
            message.update(cls.create_err_msg("ValueError", str(e)))
        except URLError as e:
            message.update(cls.create_err_msg("URLError", str(e)))
        except JSONDecodeError as e:
            message.update(cls.create_err_msg("JSONDecodeError", str(e)))
        except TypeError as e:
            message.update(cls.create_err_msg("TypeError", str(e)))
        except FileNotFoundError as e:
            message.update(cls.create_err_msg("FileNotFoundError", str(e)))
        except ConnectionError as e:
            message.update(cls.create_err_msg("ConnectionError", str(e)))
        except exceptions.SSLError as e:
            message.update(cls.create_err_msg("SSLError", str(e)))
        except OSError as e:
            message.update(cls.create_err_msg("OSError", str(e)))
        except jsonschema.exceptions.ValidationError as e:
            if e.absolute_path:
                err_msg = f"{e.message}. Error is in {' -> '.join([str(i) for i in e.absolute_path])}"
            else:
                err_msg = f"{e.message} of the root of the STAC object"
            message.update(cls.create_err_msg("ValidationError", err_msg))
        except KeyError as e:
            message.update(cls.create_err_msg("KeyError", str(e)))
        except HTTPError as e:
            message.update(cls.create_err_msg("HTTPError", str(e)))

        message["valid stac"] = valid
        cls.message.append(message)

        print(json.dumps(cls.message, indent=4))


@click.command()
@click.argument("stac_file")
@click.option(
    "--recursive", is_flag=True, help="Recursively validate all related stac objects."
)
@click.option("--core", is_flag=True, help="Validate core stac object.")
@click.option("--extensions", is_flag=True, help="Validate stac object and extensions.")
@click.option("--homegrown", is_flag=True, help="Sparkgeo validation.")
@click.option(
    "--custom",
    "-c",
    default="",
    help="Validate against a custom schema.",
)
def main(stac_file, recursive, core, extensions, custom, homegrown):
    stac = StacValidate(
        stac_file=stac_file,
        recursive=recursive,
        core=core,
        extensions=extensions,
        custom=custom,
        homegrown=homegrown,
    )
    stac.run()


if __name__ == "__main__":
    main()
