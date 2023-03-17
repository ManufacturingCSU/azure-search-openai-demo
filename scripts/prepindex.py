import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--index", help="Name of the index to create")
parser.add_argument("--datasource", help="Name of the data source to index")
parser.add_argument("--container", help="Name of the container to index")
parser.add_argument("--connectionString", help="Connection string for the data source")
parser.add_argument("--key", help="API key for the search service")


{   
    "name" : (optional on PUT; required on POST) "Name of the data source",  
    "description" : (optional) "Anything you want, or nothing at all",  
    "type" : (required) "Must be a supported data source",
    "credentials" : (required) { "connectionString" : "Connection string for your data source" },
    "container": {
        "name": "Name of the table, view, collection, or blob container you wish to index",
        "query": (optional) 
    },
    "dataChangeDetectionPolicy" : (optional) {See below for details },
    "dataDeletionDetectionPolicy" : (optional) {See below for details },
    "encryptionKey":(optional) { }
}  