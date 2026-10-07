// 6주차: Test & Coverage → SonarQube Analysis → Quality Gate → Docker Build → Push → Deploy(개인 서버) → Integration Test
// Jenkins Job "Jenkins Deploy Sonarqube" 의 Pipeline script 칸에 붙여 넣어 사용한다.
// 5주차 "Jenkins Deploy Pytest_Coverage" 파이프라인에 정적 분석(SonarQube)과 품질 게이트를 추가했다.
// 품질 게이트를 통과하지 못하면 Build 이후 단계는 실행되지 않는다 (배포 중단).
pipeline {
    agent any

    environment {
        // DockerHub
        DOCKERHUB_CREDENTIALS = 'dockerhub-credentials'   // Jenkins Credentials ID (Docker Hub Access Token)
        IMAGE_NAME     = 'heramt/fastapi-app'
        IMAGE_TAG      = "${env.BUILD_NUMBER}"            // 빌드마다 고유 태그 → 추적·롤백 가능

        // 개인 서버 (Jenkins·SonarQube와 같은 서버)
        REMOTE_USER    = 'sogang010'
        REMOTE_HOST    = '163.239.77.83'

        // GitHub
        REPO_URL       = 'https://github.com/minseok209/FastApi-Todos.git'
        BRANCH_NAME    = 'main'
        APP_DIR        = 'fastapi-app'                    // 저장소 루트 기준 앱 폴더

        // Docker — docker-compose의 FastApi-app(5001)을 지우지 않도록 이름·포트를 따로 쓴다
        CONTAINER_NAME = 'FastApi-app-sonar'
        HOST_PORT      = '5002'
        CONTAINER_PORT = '8000'
        // SONAR_TOKEN, SONAR_HOST_URL은 여기에 두지 않음 → SonarQube Analysis 단계의 withSonarQubeEnv가 주입

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
                      --cov-report=xml:"$APP_DIR/coverage.xml" \
                      --cov-report=html:htmlcov
                    # coverage.xml(Cobertura) → SonarQube Analysis 단계에서 그대로 읽어 커버리지로 표시
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

        stage('SonarQube Analysis') {
            steps {
                dir("${APP_DIR}") {
                    script {
                        def scannerHome = tool 'sonar'        // Jenkins 관리 → Tools 에 등록한 SonarQube Scanner 이름
                        // 서버 URL·토큰(sonar-token)은 withSonarQubeEnv가 이 블록 안에서만 주입 (콘솔 로그에서도 마스킹)
                        // projectKey·sources·coverage 경로는 fastapi-app/sonar-project.properties 에서 읽음
                        withSonarQubeEnv('sonarqube') {
                            sh "${scannerHome}/bin/sonar-scanner"
                        }
                    }
                }
            }
        }

        stage('Quality Gate') {
            steps {
                // SonarQube 웹훅이 결과를 알려줄 때까지 대기. 품질 기준 미달이면 파이프라인 실패 → 배포 중단
                timeout(time: 5, unit: 'MINUTES') {
                    waitForQualityGate abortPipeline: true
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
