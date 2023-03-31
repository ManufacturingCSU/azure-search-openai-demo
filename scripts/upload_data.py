import argparse
import glob
from pathlib import Path
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import ResourceExistsError
import logging

parser = argparse.ArgumentParser(
    description="Prepare documents by extracting content from PDFs, splitting content into sections, uploading to blob storage, and indexing in a search index.",
    epilog="Example: prepdocs.py '..\data\*' --storageaccount myaccount --container mycontainer --searchservice mysearch --index myindex -v",
)
parser.add_argument("files", help="Files to be processed")
parser.add_argument("--storageaccount", help="Azure Blob Storage account name")
parser.add_argument("--container", help="Azure Blob Storage container name")
parser.add_argument("--storagekey", help="Storage key token")
parser.add_argument(
    "--overwrite_files",
    type=bool,
    help="If True, existing files will be overwritten",
    default=False,
)
args = parser.parse_args()

default_creds = DefaultAzureCredential()

storage_credential = AzureNamedKeyCredential(
    name=args.storageaccount, key=args.storagekey
)

blob_service = BlobServiceClient(
    account_url=f"https://{args.storageaccount}.blob.core.windows.net",
    credential=storage_credential,
)
blob_container = blob_service.get_container_client(args.container)
overwrite = args.overwrite_files

for filename in glob.glob(args.files):
    with open(filename, "rb") as f:
        blob_name = Path(filename).name
        try:
            blob_container.upload_blob(blob_name, f, overwrite=overwrite)
        except ResourceExistsError:
            logging.info(f"{blob_name} already exists.")
