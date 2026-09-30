// 5주차: 단위 테스트(Test & Coverage) → Docker Build → Push → Deploy(팀 서버) → 통합 테스트(Integration Test)
// Jenkins Job "Jenkins Deploy Pytest_Coverage" 의 Pipeline script 칸에 붙여 넣어 사용한다.
// 4주차 "Jenkins Delpoy Docker direct" 와 같은 자격증명·이미지를 쓰고, 앞에 테스트 단계를, 뒤에 API 테스트 단계를 붙였다.
pipeline {
    agent any

    environment {
        // DockerHub
        DOCKERHUB_CREDENTIALS = 'dockerhub-credentials'   // Jenkins Credentials ID (Docker Hub Access Token)
        IMAGE_NAME     = 'heramt/fastapi-app'
        IMAGE_TAG      = "${env.BUILD_NUMBER}"            // 빌드마다 고유 태그 → 추적·롤백 가능

        // 팀 서버
        REMOTE_USER    = 'sogang003'
        REMOTE_HOST    = '163.239.77.76'

        // GitHub
        REPO_URL       = 'https://github.com/minseok209/FastApi-Todos.git'
        BRANCH_NAME    = 'main'
        APP_DIR        = 'fastapi-app'                    // 저장소 루트 기준 앱 폴더

        // Docker — 팀 서버 계정을 팀원이 공유하므로 본인 이름·포트 대역(8050~)으로 구분
        CONTAINER_NAME = 'fastapi-pytest-minseok'         // 4주차 fastapi-app2-minseok(8054)와 별개
        HOST_PORT      = '8055'
        CONTAINER_PORT = '8000'

        // Jenkins 실패 알림 메일 — 붙여 넣을 때 본인 주소로 바꾼다 (저장소에는 올리지 않음)
        NOTIFY_EMAIL   = '[받을 이메일 주소]'
    }

    options {
        timeout(time: 20, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    stages {
        stage('Checkout') {
            steps {
                git url: "${REPO_URL}", branch: "${BRANCH_NAME}"
            }
        }

        stage('Setup Environment & Install Dependencies') {
            steps {
                sh '''
                    python3 --version    # 3.10 이상 필요 (권장 3.12+)
                    python3 -m venv venv
                    . venv/bin/activate
                    python -m pip install --upgrade pip
                    pip install -r "$APP_DIR/requirements.txt"
                '''
            }
        }

        stage('Test & Coverage') {
            steps {
                sh '''
                    . venv/bin/activate
                    mkdir -p pytest_report
                    python -m pytest "$APP_DIR/tests" \
                      --html=pytest_report/report.html \
                      --self-contained-html \
                      --cov="$APP_DIR" \
                      --cov-config="$APP_DIR/pyproject.toml" \
                      --cov-report=html:htmlcov
                '''
            }
            post {
                always {
                    publishHTML(target: [
                        reportName : 'Pytest HTML Report',
                        reportDir  : 'pytest_report',
                        reportFiles: 'report.html',
                        keepAll    : true,
                        alwaysLinkToLastBuild: true,
                        allowMissing: true
                    ])
                    publishHTML(target: [
                        reportName : 'Coverage Report',
                        reportDir  : 'htmlcov',
                        reportFiles: 'index.html',
                        keepAll    : true,
                        alwaysLinkToLastBuild: true,
                        allowMissing: true
                    ])
                }
            }
        }

        stage('Build') {
            steps {
                dir("${APP_DIR}") {
                    script {
                        docker.build("${IMAGE_NAME}:${IMAGE_TAG}", "--pull .")
                    }
                }
            }
        }

        stage('Push') {
            steps {
                script {
                    docker.withRegistry('https://index.docker.io/v1/', DOCKERHUB_CREDENTIALS) {
                        def image = docker.image("${IMAGE_NAME}:${IMAGE_TAG}")
                        image.push()           // :빌드번호
                        image.push('latest')   // :latest 도 함께 갱신
                    }
                }
            }
        }

        stage('Deploy') {
            steps {
                sshagent(credentials: ['deploy-key']) {
                    sh '''
ssh -o StrictHostKeyChecking=accept-new ${REMOTE_USER}@${REMOTE_HOST} \
  "IMAGE='${IMAGE_NAME}:${IMAGE_TAG}' CONTAINER_NAME='${CONTAINER_NAME}' HOST_PORT='${HOST_PORT}' CONTAINER_PORT='${CONTAINER_PORT}' bash -se" <<'ENDSSH'
set -euo pipefail

docker pull "$IMAGE"
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
docker run -d --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -p "$HOST_PORT:$CONTAINER_PORT" \
  "$IMAGE"
docker ps --filter "name=$CONTAINER_NAME"
ENDSSH
'''
                }
            }
        }

        stage('Integration Test') {      // 통합 테스트: 배포된 서버에 실제 HTTP 요청
            steps {
                sh '''
                    . venv/bin/activate
                    mkdir -p api_report
                    BASE_URL="http://$REMOTE_HOST:$HOST_PORT" \
                    python -m pytest api-tests \
                      --html=api_report/report.html \
                      --self-contained-html
                '''
            }
            post {
                always {
                    publishHTML(target: [
                        reportName : 'Integration Test Report',
                        reportDir  : 'api_report',
                        reportFiles: 'report.html',
                        keepAll    : true,
                        alwaysLinkToLastBuild: true,
                        allowMissing: true
                    ])
                }
            }
        }
    }

    post {
        failure {
            mail to: "${NOTIFY_EMAIL}",
                 subject: "[Jenkins] 빌드 실패: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                 body: """Jenkins 빌드가 실패했습니다.

Job: ${env.JOB_NAME}
Build: #${env.BUILD_NUMBER}
Console: ${env.BUILD_URL}console
"""
        }
        always {
            sh 'docker image prune -f || true'   // Jenkins 서버에 쌓이는 이미지 정리
            echo 'Pipeline completed.'
        }
    }
}
