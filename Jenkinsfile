// Build and deploy AWS Lambda container image to ECR.
pipeline {
    agent any

    environment {
        AWS_REGION = 'eu-central-1'
        ECR_REGISTRY = '423623826655.dkr.ecr.eu-central-1.amazonaws.com'
        ECR_REPOSITORY = 'vtt-subtitles-comparison-lambda'
        LAMBDA_FUNCTION_NAME = 'vtt-subtitles-comparison'
        LAMBDA_ROLE_ARN = 'arn:aws:iam::423623826655:role/lambda-role'
        FUNCTION_URL_AUTH_TYPE = 'NONE'
        FUNCTION_URL_PERMISSION_SID = 'AllowPublicFunctionUrlInvoke'
        IMAGE_URI = "${ECR_REGISTRY}/${ECR_REPOSITORY}:latest"
    }

    options {
        timestamps()
        timeout(time: 60, unit: 'MINUTES')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('AWS ECR Login') {
            steps {
                sh '''
                    set -e
                    aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}
                '''
            }
        }

        stage('Docker build') {
            steps {
                sh '''
                    set -e
                    docker build -f Dockerfile -t ${ECR_REPOSITORY}:latest .
                    docker tag ${ECR_REPOSITORY}:latest ${IMAGE_URI}
                '''
            }
        }

        stage('AWS ECR push') {
            steps {
                sh '''
                    set -e
                    docker push ${IMAGE_URI}
                '''
            }
        }

        stage('Deploy Lambda from image') {
            steps {
                sh '''
                    set -e
                    if aws lambda get-function --function-name "${LAMBDA_FUNCTION_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1; then
                        echo "Updating existing Lambda ${LAMBDA_FUNCTION_NAME}..."
                        aws lambda update-function-code \
                            --function-name "${LAMBDA_FUNCTION_NAME}" \
                            --image-uri "${IMAGE_URI}" \
                            --region "${AWS_REGION}"
                    else
                        echo "Creating Lambda ${LAMBDA_FUNCTION_NAME} from image..."
                        aws lambda create-function \
                            --function-name "${LAMBDA_FUNCTION_NAME}" \
                            --package-type Image \
                            --code "ImageUri=${IMAGE_URI}" \
                            --role "${LAMBDA_ROLE_ARN}" \
                            --region "${AWS_REGION}"
                    fi
                '''
            }
        }

        stage('Ensure public Lambda Function URL') {
            steps {
                sh '''
                    set -e

                    if aws lambda get-function-url-config \
                        --function-name "${LAMBDA_FUNCTION_NAME}" \
                        --region "${AWS_REGION}" >/dev/null 2>&1; then
                        echo "Updating Function URL auth type to ${FUNCTION_URL_AUTH_TYPE}..."
                        aws lambda update-function-url-config \
                            --function-name "${LAMBDA_FUNCTION_NAME}" \
                            --auth-type "${FUNCTION_URL_AUTH_TYPE}" \
                            --region "${AWS_REGION}"
                    else
                        echo "Creating Function URL with auth type ${FUNCTION_URL_AUTH_TYPE}..."
                        aws lambda create-function-url-config \
                            --function-name "${LAMBDA_FUNCTION_NAME}" \
                            --auth-type "${FUNCTION_URL_AUTH_TYPE}" \
                            --region "${AWS_REGION}"
                    fi

                    set +e
                    ADD_PERMISSION_OUTPUT=$(
                        aws lambda add-permission \
                            --function-name "${LAMBDA_FUNCTION_NAME}" \
                            --statement-id "${FUNCTION_URL_PERMISSION_SID}" \
                            --action lambda:InvokeFunctionUrl \
                            --principal "*" \
                            --function-url-auth-type "${FUNCTION_URL_AUTH_TYPE}" \
                            --region "${AWS_REGION}" 2>&1
                    )
                    ADD_PERMISSION_EXIT_CODE=$?
                    set -e

                    if [ "${ADD_PERMISSION_EXIT_CODE}" -ne 0 ]; then
                        if printf '%s' "${ADD_PERMISSION_OUTPUT}" | rg -q "ResourceConflictException"; then
                            echo "Function URL permission already exists."
                        else
                            printf '%s\n' "${ADD_PERMISSION_OUTPUT}"
                            exit "${ADD_PERMISSION_EXIT_CODE}"
                        fi
                    else
                        echo "Function URL permission created."
                    fi

                    aws lambda get-function-url-config \
                        --function-name "${LAMBDA_FUNCTION_NAME}" \
                        --region "${AWS_REGION}" \
                        --query 'FunctionUrl' \
                        --output text
                '''
            }
        }
    }
}
