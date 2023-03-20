import os
import argparse
import glob
import io
import re
import time
import datetime
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
    SearchableField,
    ComplexField,
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
parser.add_argument(
    "--container",
    help="Source container in Azure Storage Account.",
)
parser.add_argument(
    "--connection_string",
    help="Connection string from Azure Storage Account",
)
parser.add_argument(
    "--datasource_name",
    help="Name for search indexer data source",
)
parser.add_argument(
    "--function_app_name",
    help="Name of Azure Function App hosting the Azure Function",
)
parser.add_argument(
    "--function_key",
    help="API key for Azure Function",
)
parser.add_argument(
    "--indexer_name", default="openai-indexer", help="Name of Cognitive Search indexer."
)
parser.add_argument("--skillset_name", default="openai-data-skill")
args = parser.parse_args()

# Use the current user identity to connect to Azure services unless a key is explicitly set for any of them
default_creds = DefaultAzureCredential() if args.searchkey == None else None
search_creds = (
    default_creds if args.searchkey == None else AzureKeyCredential(args.searchkey)
)
endpoint = f"https://{args.searchservice}.search.windows.net/"


def create_search_index():
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
                    name="summary",
                    type="Edm.String",
                ),
                SimpleField(
                    name="title",
                    type="Edm.String",
                ),
                SimpleField(
                    name="author",
                    type="Edm.String",
                ),
                SearchableField(
                    name="keywords",
                    collection=True,
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
        result = index_client.create_index(index)
    return result


def create_datasource():
    # Here we create a datasource. As mentioned in the description we have stored it in
    # "searchcontainer"
    ds_client = SearchIndexerClient(endpoint, search_creds)
    datasource_name = (
        args.datasource_name
        if args.datasource_name is not None
        else args.container + "-datasource"
    )
    if datasource_name not in ds_client.get_data_source_connection_names():
        container = SearchIndexerDataContainer(name=args.container)
        data_source_connection = SearchIndexerDataSourceConnection(
            name=datasource_name,
            type="azureblob",
            connection_string=args.connection_string,
            container=container,
        )
        data_source = ds_client.create_data_source_connection(data_source_connection)
    else:
        data_source = ds_client.get_data_source_connection(datasource_name)
    return data_source


def create_skillset():
    client = SearchIndexerClient(endpoint, search_creds)
    if args.skillset_name not in client.get_skillset_names():
        inp = InputFieldMappingEntry(name="text", source="/document/content")
        summary = OutputFieldMappingEntry(name="summary", target_name="summary")
        keywords = OutputFieldMappingEntry(name="keywords", target_name="keywords")
        title = OutputFieldMappingEntry(name="title", target_name="title")
        author = OutputFieldMappingEntry(name="author", target_name="author")
        outputs = [summary, keywords, title, author]
        s = WebApiSkill(
            name="openai-skill",
            uri=f"https://{args.function_app_name}.azurewebsites.net/api/OpenAISkill",
            http_headers={"x-functions-key": args.function_key},
            http_method="POST",
            inputs=[inp],
            outputs=outputs,
        )
        skillset = SearchIndexerSkillset(
            name=args.skillset_name, skills=[s], description="Document search skillset"
        )
        result = client.create_skillset(skillset)
    else:
        result = client.get_skillset(args.skillset_name)
    return result


def create_indexer():
    skillset_name = create_skillset().name
    print("Skillset is created")

    ds_name = create_datasource().name
    print("Data source is created")

    ind_name = create_search_index().name
    print("Index is created")

    # we pass the data source, skillsets and targeted index to build an indexer
    parameters = IndexingParameters(configuration={"parsingMode": "jsonArray"})
    indexer = SearchIndexer(
        name=args.indexer_name,
        data_source_name=ds_name,
        target_index_name=ind_name,
        skillset_name=skillset_name,
        parameters=parameters,
    )

    indexer_client = SearchIndexerClient(endpoint, search_creds)
    indexer_client.create_indexer(indexer)  # create the indexer

    # to get an indexer
    result = indexer_client.get_indexer(args.indexer_name)
    print(result)

    # To run an indexer, we can use run_indexer()
    indexer_client.run_indexer(result.name)

    # Using create or update to schedule an indexer

    schedule = IndexingSchedule(interval=datetime.timedelta(hours=24))
    result.schedule = schedule
    updated_indexer = indexer_client.create_or_update_indexer(result)

    print(updated_indexer)

    # get the status of an indexer
    indexer_client.get_indexer_status(updated_indexer.name)


create_indexer()
