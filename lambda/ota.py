import io
import os
import json
import pandas
import hashlib
import uuid
from tabula import read_pdf
import requests
import boto3
from bs4 import BeautifulSoup


def lambda_handler(event, context):
    try:
        if os.getenv("AWS_SAM_LOCAL") == "true":
            dynamodb = boto3.resource(
                "dynamodb",
                endpoint_url="http://dynamodb-local:8000",
                region_name="ap-northeast-1",
                aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
            )
        else:
            dynamodb = boto3.resource("dynamodb")

        baseUrl = (
            "https://www.city.ota.tokyo.jp/seikatsu/kodomo/hoiku/hoikushisetsu_nyukibo/"
        )
        url = baseUrl + "aki-joho.html"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a")
        for link in links:
            if ".pdf" in link.get("href", []):
                version = link.get("href").split("/")[1].replace(".pdf", "")
                response = requests.get(baseUrl + link.get("href"))
                pdfFile = io.BytesIO(response.content)
        tableList = dynamodb.tables.all()
        tableName = "ota" + version
        for existingTable in tableList:
            if tableName == existingTable._name:
                return {"statusCode": 200, "body": "succeeded"}

        df = read_pdf(pdfFile, pages="all", lattice=True)
        dataList = pandas.concat(df)
        data = dataList.rename(
            {
                "番号": "list_number",
                "種別": "type",
                "(延)": "can_extend",
                "保育所": "name",
                "開始": "starts_at",
                "0歳": "0_year_old",
                "1歳": "1_year_old",
                "2歳": "2_years_old",
                "3歳": "3_years_old",
                "4歳": "4_years_old",
                "5歳": "5_years_old",
                "緊急": "emergency",
                "所在地": "address",
                "電話": "phone",
            },
            axis="columns",
        ).drop(columns=["Unnamed: 0", "Unnamed: 1"])
        data.loc[:, "can_extend"] = data["can_extend"] == "*"
        data.loc[:, "emergency"] = data["emergency"] == "★"
        data["id"] = data.apply(
            lambda x: str(
                uuid.UUID(hex=hashlib.md5(repr(x["phone"]).encode("UTF-8")).hexdigest())
            ),
            axis=1,
        )
        attributes = [
            "list_number",
            "0_year_old",
            "1_year_old",
            "2_years_old",
            "3_years_old",
            "4_years_old",
            "5_years_old",
        ]

        for attribute in attributes:
            data.loc[pandas.isna(data[attribute]), attribute] = 0
            data.loc[data[attribute] == "×", attribute] = -1
            data[attribute] = pandas.to_numeric(
                data[attribute], errors="coerce", downcast="signed"
            )

        result = data.to_json(orient="records")
        records = json.loads(result)

        table = dynamodb.create_table(
            TableName=tableName,
            KeySchema=[
                {"AttributeName": "id", "KeyType": "HASH"},
                {"AttributeName": "list_number", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "id", "AttributeType": "S"},
                {"AttributeName": "list_number", "AttributeType": "N"},
            ],
            BillingMode="PROVISIONED",
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        table.wait_until_exists()

        if os.getenv("AWS_SAM_LOCAL") != "true":
            autoScaling = boto3.client(
                "application-autoscaling",
            )
            autoScaling.register_scalable_target(
                ServiceNamespace="dynamodb",
                ResourceId="table/" + tableName,
                ScalableDimension="dynamodb:table:ReadCapacityUnits",
                MinCapacity=1,
                MaxCapacity=100,
            )
            autoScaling.register_scalable_target(
                ServiceNamespace="dynamodb",
                ResourceId="table/" + tableName,
                ScalableDimension="dynamodb:table:WriteCapacityUnits",
                MinCapacity=1,
                MaxCapacity=100,
            )
            targetValue = 70
            scale = 60
            autoScaling.put_scaling_policy(
                ServiceNamespace="dynamodb",
                ResourceId="table/" + tableName,
                PolicyType="TargetTrackingScaling",
                PolicyName="ScaleDynamoDBReadCapacityUtilization",
                ScalableDimension="dynamodb:table:ReadCapacityUnits",
                TargetTrackingScalingPolicyConfiguration={
                    "TargetValue": targetValue,
                    "PredefinedMetricSpecification": {
                        "PredefinedMetricType": "DynamoDBReadCapacityUtilization"
                    },
                    "ScaleOutCooldown": scale,
                    "ScaleInCooldown": scale,
                },
            )
            autoScaling.put_scaling_policy(
                ServiceNamespace="dynamodb",
                ResourceId="table/" + tableName,
                PolicyType="TargetTrackingScaling",
                PolicyName="ScaleDynamoDBWriteCapacityUtilization",
                ScalableDimension="dynamodb:table:WriteCapacityUnits",
                TargetTrackingScalingPolicyConfiguration={
                    "TargetValue": targetValue,
                    "PredefinedMetricSpecification": {
                        "PredefinedMetricType": "DynamoDBWriteCapacityUtilization"
                    },
                    "ScaleOutCooldown": scale,
                    "ScaleInCooldown": scale,
                },
            )

        with table.batch_writer(overwrite_by_pkeys=["id"]) as batch:
            for record in records:
                batch.put_item(Item=record)
        return {"statusCode": 200, "body": "succeeded"}
    except Exception as e:
        # Handle any other errors that may occur
        error_message = f"Error: {str(e)}"
        print(str(e))

        # Return the error message as a JSON object with a 400 status code
        return {"statusCode": 400, "body": "error"}
