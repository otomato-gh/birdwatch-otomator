# BirdWatch Otomator

A python-based K8S controller to manage canary releases with Istio service mesh

Supports querying Prometheus for canary health metrics.

Can be configured to send Slack notifications.

Install with helm by running: `helm install ./helm --name birdwatch --set slackToken=<your-slack-token> --set prometheusUrl=<your-slack-token>`


