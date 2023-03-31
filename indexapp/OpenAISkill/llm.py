import os
import json
from typing import Optional, Tuple
from copy import deepcopy
from enum import Enum


from pydantic import BaseModel

from langchain.llms import OpenAI, AzureOpenAI
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain import OpenAI
from langchain.prompts import PromptTemplate
from langchain.text_splitter import CharacterTextSplitter
from langchain.chains.summarize import load_summarize_chain
from langchain.docstore.document import Document as LLMDocument
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")
api_type = os.getenv("OPENAI_API_TYPE")
if api_type == "azure":
    openai.api_type = api_type
    openai.api_base = os.getenv("OPENAI_API_BASE")
    openai.api_version = os.getenv("OPENAI_API_VERSION")
davinci_engine = os.getenv("DAVINCI_ENGINE", None)
turbo = os.getenv("TURBO_ENGINE", None)


class Chat(BaseModel):
    new_input: str
    user_inputs: list[str]
    bot_outputs: list[str]
    doc_id: int
    document: Optional[str] = None


class DocumentCoverage(str, Enum):
    ALL="all"
    FIRST="first-success"


class Field(BaseModel):
    name: str
    template: str
    type: str
    document_coverage: DocumentCoverage = DocumentCoverage.ALL


def process_result(result: str, field_type: str):
    if field_type == "str":
        return result
    elif  field_type == "list":
        return [res.strip() for res in result]
    elif field_type == "object":
        return json.loads(result)
    

class TextExtraction(object):
    def __init__(
        self,
        text: str,
        fields: Tuple[Field]
    ):
        self._text = text
        self._fields = fields
        self._split_document()

    def _split_document(self):
        # Summary prep
        text_splitter = CharacterTextSplitter(separator="\n")
        texts = text_splitter.split_text(self._text)
        self._summary_splits = [LLMDocument(page_content=t) for t in texts]

    @property
    def full_text(self):
        return self._text

    @property
    def summary_splits(self):
        return [split.page_content for split in self._summary_splits]

    @staticmethod
    def _create_chain(template):
        if api_type == "azure":
            llm = AzureOpenAI(temperature=0, deployment_name=davinci_engine)
        else:
            llm = OpenAI(temperature=0)
        prompt = PromptTemplate(
            input_variables=["text"], template=template
        )
        return LLMChain(llm=llm, prompt=prompt)

    def process_document(self):
        document_output = {}
        for field in self._fields:
            name = field.name
            template = field.template
            chain = self._create_chain(template)
            for text_doc in self._summary_splits:
                res = chain.run(text_doc.page_content)
                document_output[name] = process_result(res)
        return document_output
            

    @staticmethod
    def _keyword_chain():
        if api_type == "azure":
            llm = AzureOpenAI(temperature=0, deployment_name=davinci_engine)
        else:
            llm = OpenAI(temperature=0)
        keyword_template = (
            "Extract at most ten keywords from the text below. If there are no keywords found,"
            "return 'WARNING: No keywords identified'."
            "\n\n{text}\n\nKeywords:"
        )
        keyword_prompt = PromptTemplate(
            input_variables=["text"], template=keyword_template
        )
        return LLMChain(llm=llm, prompt=keyword_prompt)

    @property
    def keywords(self):
        if self._keywords is None:
            keyword_chain = self._keyword_chain()
            keywords = []
            for text_doc in self._summary_splits:
                res = keyword_chain.run(text_doc.page_content)
                if "WARNING" not in res:
                    keywords += [keyword.strip() for keyword in res.split(",")]
                    break
            self._keywords = list(set(keywords))
        return self._keywords

    @staticmethod
    def _title_chain():
        if api_type == "azure":
            llm = AzureOpenAI(temperature=0, deployment_name=davinci_engine)
        else:
            llm = OpenAI(temperature=0)
        title_template = (
            "What is the title of the paper below?. If there is no title found,"
            "return 'WARNING: No title identified'."
            "\n\n{text}\n\nTITLE:"
        )
        title_prompt = PromptTemplate(input_variables=["text"], template=title_template)
        return LLMChain(llm=llm, prompt=title_prompt)

    @property
    def title(self):
        if self._title is None:
            title_chain = self._title_chain()
            title = ""
            for text_doc in self._summary_splits:
                res = title_chain.run(text_doc.page_content)
                if "WARNING" not in res:
                    title += res.strip()
                    break
            self._title = title
        return self._title

    def _process_summary(self):
        if api_type == "azure":
            llm = AzureOpenAI(temperature=0, deployment_name=davinci_engine)
        else:
            llm = OpenAI(temperature=0)

        prompt_template = """Your job is to produce a concise and informative summary of the following:


        {text}


        INFORMATIVE SUMMARY:"""
        PROMPT = PromptTemplate(template=prompt_template, input_variables=["text"])
        chain = load_summarize_chain(
            llm,
            chain_type="map_reduce",
            return_intermediate_steps=True,
            map_prompt=PROMPT,
            combine_prompt=PROMPT,
        )
        outputs = chain(
            {"input_documents": self._summary_splits}, return_only_outputs=True
        )
        self._summary = outputs["output_text"].strip()
        self._intermediate_summaries = [
            sum.strip() for sum in outputs["intermediate_steps"]
        ]

    @property
    def intermediate_summaries(self):
        if self._intermediate_summaries is None:
            self._process_summary()
        return self._intermediate_summaries

    @property
    def summary(self):
        if self._summary is None:
            self._process_summary()
        return self._summary
