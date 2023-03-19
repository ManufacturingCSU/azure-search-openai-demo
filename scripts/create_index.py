import os
import argparse
import glob
import io
import re
import time
from pypdf import PdfReader, PdfWriter
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes.models import *
from azure.search.documents import SearchClient
from azure.search.documents.indexes.models import (
    SearchIndexerDataContainer,
    SearchIndex,
    SearchIndexer,
    SimpleField,
    SearchFieldDataType,
    EntityRecognitionSkill,
    InputFieldMappingEntry,
    OutputFieldMappingEntry,
    SearchIndexerSkillset,
    CorsOptions,
    IndexingSchedule,
    SearchableField,
    IndexingParameters,
    SearchIndexerDataSourceConnection,
    OcrSkill,
    WebApiSkill,
)

MAX_SECTION_LENGTH = 1000
SENTENCE_SEARCH_LIMIT = 100
SECTION_OVERLAP = 100

parser = argparse.ArgumentParser(
    description="Create search index for enterprise data with ChatGPT.",
)
parser.add_argument(
    "--searchservice",
    help="Name of the Azure Cognitive Search service where content should be indexed (must exist already)",
)
parser.add_argument(
    "--index",
    help="Name of the Azure Cognitive Search index where content should be indexed (will be created if it doesn't exist)",
)
parser.add_argument(
    "--searchkey",
    required=False,
    help="Optional. Use this Azure Cognitive Search account key instead of the current user identity to login (use az login to set current user for Azure)",
)
args = parser.parse_args()

# Use the current user identity to connect to Azure services unless a key is explicitly set for any of them
default_creds = DefaultAzureCredential() if args.searchkey == None else None
search_creds = (
    default_creds if args.searchkey == None else AzureKeyCredential(args.searchkey)
)


def create_search_index():
    endpoint = f"https://{args.searchservice}.search.windows.net/"
    index_client = SearchIndexClient(endpoint=endpoint, credential=search_creds)
    if args.index not in index_client.list_index_names():
        index = SearchIndex(
            name=args.index,
            fields=[
                SimpleField(name="id", type="Edm.String", key=True),
                SearchableField(
                    name="content", type="Edm.String", analyzer_name="en.microsoft"
                ),
                SimpleField(
                    name="category", type="Edm.String", filterable=True, facetable=True
                ),
                SimpleField(
                    name="sourcepage",
                    type="Edm.String",
                    filterable=True,
                    facetable=True,
                ),
                SimpleField(
                    name="sourcefile",
                    type="Edm.String",
                    filterable=True,
                    facetable=True,
                ),
            ],
            semantic_settings=SemanticSettings(
                configurations=[
                    SemanticConfiguration(
                        name="default",
                        prioritized_fields=PrioritizedFields(
                            title_field=None,
                            prioritized_content_fields=[
                                SemanticField(field_name="content")
                            ],
                        ),
                    )
                ]
            ),
        )
        index_client.create_index(index)


create_search_index()
