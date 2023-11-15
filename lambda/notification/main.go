package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go/aws"
	"github.com/aws/aws-sdk-go/aws/awserr"
	"github.com/aws/aws-sdk-go/aws/credentials"
	"github.com/aws/aws-sdk-go/aws/session"
	"github.com/aws/aws-sdk-go/service/ses"
	"github.com/aws/aws-sdk-go/service/sqs"
	"github.com/guregu/dynamo"
	"golang.org/x/exp/slices"
)

var sqsClient *sqs.SQS
var ddbClient *dynamo.DB
var sesClient *ses.SES

func init() {
	// Initialize the AWS session and SQS client
	sess := session.Must(session.NewSession())
	if os.Getenv("AWS_SAM_LOCAL") == "true" {
		ddbClient = dynamo.New(sess, &aws.Config{
			Region:      aws.String("ap-northeast-1"),
			Endpoint:    aws.String("http://dynamodb-local:8000"),
			DisableSSL:  aws.Bool(true),
			Credentials: credentials.NewStaticCredentials("dummy", "dummy", "dummy"),
		})
	} else {
		ddbClient = dynamo.New(sess, &aws.Config{Region: aws.String("ap-northeast-1")})
	}
	sesClient = ses.New(sess, &aws.Config{Region: aws.String("ap-northeast-1")})
	sqsClient = sqs.New(sess)
}

type ota struct {
	ID            string `json:"id" dynamo:"id,hash"`
	Address       string `json:"address" dynamo:"address"`
	Type          string `json:"type" dynamo:"type"`
	Name          string `json:"name" dynamo:"name"`
	Phone         string `json:"phone" dynamo:"phone"`
	CanExtend     bool   `json:"can_extend" dynamo:"can_extend"`
	Emergency     bool   `json:"emergency" dynamo:"emergency"`
	StartsAt      string `json:"starts_at" dynamo:"starts_at"`
	ListNumber    int    `json:"list_number" dynamo:"list_number,range"`
	ZeroYearOld   int    `json:"0_year_old" dynamo:"0_year_old"`
	OneYearOld    int    `json:"1_year_old" dynamo:"1_year_old"`
	TwoYearsOld   int    `json:"2_years_old" dynamo:"2_years_old"`
	ThreeYearsOld int    `json:"3_years_old" dynamo:"3_years_old"`
	FourYearsOld  int    `json:"4_years_old" dynamo:"4_years_old"`
	FiveYearsOld  int    `json:"5_years_old" dynamo:"5_years_old"`
}

type user struct {
	Area        string   `json:"area" dynamo:"area,hash"`
	Email       string   `json:"email" dynamo:"email"`
	TargetIds   []string `json:"target_ids" dynamo:"target_ids"`
	TargetClass int      `json:"target_class" dynamo:"target_class"`
}

func processSQSMessage(ctx context.Context, event events.SQSEvent) error {
	for _, message := range event.Records {
		area := *&message.Body
		areaTable := ddbClient.Table(area)
		userTable := ddbClient.Table("users")
		var users []user
		userErr := userTable.Batch("area").Get(dynamo.Keys{area}).All(&users)
		if userErr != nil {
			return userErr
		}
		var schools []ota
		schoolErr := areaTable.Scan().All(&schools)
		if schoolErr != nil {
			return schoolErr
		}
		time := time.Now()
		body := fmt.Sprintf("%d年%d月時点での各保育園空き状況は以下の通りです。\n\n\n", time.Year(), time.Month())
		for _, user := range users {
			var targets []ota
			for _, school := range schools {
				if slices.Contains(user.TargetIds, school.ID) {
					targets = append(targets, school)
				}
			}
			for _, target := range targets {
				var targetValue int
				switch user.TargetClass {
				case 0:
					targetValue = target.ZeroYearOld
				case 1:
					targetValue = target.OneYearOld
				case 2:
					targetValue = target.TwoYearsOld
				case 3:
					targetValue = target.ThreeYearsOld
				case 4:
					targetValue = target.FourYearsOld
				default:
					targetValue = target.FiveYearsOld
				}
				body += fmt.Sprintf("%s(%d歳児クラス): %d\n", target.Name, user.TargetClass, targetValue)
			}
			body += "\n\n詳細は http://google.com でも確認できます。"
			input := &ses.SendEmailInput{
				Destination: &ses.Destination{
					ToAddresses: []*string{aws.String(user.Email)},
				},
				Message: &ses.Message{
					Body: &ses.Body{
						Text: &ses.Content{
							Data: aws.String(body),
						},
					},
					Subject: &ses.Content{
						Data: aws.String("保育園空き枠のお知らせ"),
					},
				},
				Source: aws.String("kaserj1119@gmail.com"),
			}

			_, err := sesClient.SendEmail(input)

			if err != nil {
				if aerr, ok := err.(awserr.Error); ok {
					switch aerr.Code() {
					case ses.ErrCodeMessageRejected:
						fmt.Println(ses.ErrCodeMessageRejected, aerr.Error())
					case ses.ErrCodeMailFromDomainNotVerifiedException:
						fmt.Println(ses.ErrCodeMailFromDomainNotVerifiedException, aerr.Error())
					case ses.ErrCodeConfigurationSetDoesNotExistException:
						fmt.Println(ses.ErrCodeConfigurationSetDoesNotExistException, aerr.Error())
					default:
						fmt.Println(aerr.Error())
					}
				} else {
					// Print the error, cast err to awserr.Error to get the Code and
					// Message from an error.
					fmt.Println(err.Error())
				}
			}

		}
		return nil
	}

	return nil
}

func main() {
	lambda.Start(processSQSMessage)
}
