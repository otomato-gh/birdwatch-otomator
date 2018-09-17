import json
import yaml
from kubernetes import client, config, watch
import os, time
import requests
import monkeypatches.monkeypatch

DOMAIN = "otomato.link"
PROM_URL = "http://prometheus.159.8.233.5.nip.io" # http://prometheus.default.svc.cluster.local"
def check_canary_health():
    print("Checking canary health ")
    query_string = 'sum_over_time(flask_request_count{endpoint="/version",http_status="500",instance="aleph.games.svc.cluster.local:8000",job="aleph",method="GET"}[5m])'
    response = requests.get(PROM_URL+"/api/v1/query?query="+query_string).content
    metric = json.loads(response)
    print metric["data"]["result"][0]["value"][1]

    time.sleep(5)
    return True


def update_destination_rule(crds, namespace, service):
    destination_rule = crds.get_namespaced_custom_object("networking.istio.io", 
                                                         "v1alpha3", 
                                                         namespace,
                                                         "destinationrules",
                                                         service)
    #update destination rule
    canary_index = next((index for (index, d) in enumerate(destination_rule["spec"]["subsets"]) 
                                                                if d["name"] == "canary"), None)
    destination_rule["spec"]["subsets"][canary_index]["labels"]["version"] = obj["spec"]["canary_version"]
    crds.patch_namespaced_custom_object("networking.istio.io", 
                                        "v1alpha3", 
                                        namespace, 
                                        "destinationrules", 
                                        name, 
                                        destination_rule)
     

def update_virtualservice(crds, obj):
    metadata = obj.get("metadata")
    if not metadata:
        print("No metadata in object, skipping: %s" % json.dumps(obj, indent=1))
        return
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    obj["spec"]["inprocess"] = True
    service = obj["spec"]["service"]
    print("Updating: %s" % name)
    canary_healthy = True
    prodWeight = 99
    canaryWeight = 1
    
    update_destination_rule(crds, namespace, service)

    vs = crds.get_namespaced_custom_object("networking.istio.io", "v1alpha3", namespace, "virtualservices", service)
    canary_index = next((index for (index, d) in enumerate(vs["spec"]["http"][0]["route"]) 
                                                                if d["destination"]["subset"] == "canary"), None)
    prod_index = next((index for (index, d) in enumerate(vs["spec"]["http"][0]["route"]) 
                                                                if d["destination"]["subset"] == "production"), None)
    vs["metadata"].pop("annotations")
    vs["metadata"].pop("resourceVersion")    
    vs["metadata"].pop("uid")   
    vs["metadata"].pop("selfLink") 
    
    
    while canary_healthy and canaryWeight <=100:
        print("canary %s prod %s " %(canaryWeight, prodWeight))
        vs["spec"]["http"][0]["route"][canary_index]["weight"] = canaryWeight
        vs["spec"]["http"][0]["route"][prod_index]["weight"] = prodWeight
        crds.patch_namespaced_custom_object("networking.istio.io", "v1alpha3", namespace, "virtualservices", name, vs)
        canary_healthy = check_canary_health()
        prodWeight-=1
        canaryWeight+=1
    rollback = """
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: {name}
spec:
  hosts:
  - {name}
  http:
  - route:
    - destination:
        host: {name}
        port:
          number: 80
        subset: v02
      weight: 100
    - destination:
        host: aleph
        port:
          number: 80
        subset: v03
      weight: 0""".format(name=name)
    crds.patch_namespaced_custom_object("networking.istio.io", "v1alpha3", namespace, "virtualservices", name, yaml.load(rollback))  

if __name__ == "__main__":
    if 'KUBERNETES_PORT' in os.environ:
        config.load_incluster_config()
        definition = '/tmp/bird.yml'
    else:
        config.load_kube_config()
        definition = 'bird.yml'
    configuration = client.Configuration()
    configuration.assert_hostname = False
    api_client = client.api_client.ApiClient(configuration=configuration)
    v1 = client.ApiextensionsV1beta1Api(api_client)
    current_crds = [x['spec']['names']['kind'].lower() for x in v1.list_custom_resource_definition().to_dict()['items']]
    if 'birdwatch' not in current_crds:
        print("Creating birdwatch definition")
        with open(definition) as data:
            body = yaml.load(data)
        v1.create_custom_resource_definition(body)
    crds = client.CustomObjectsApi(api_client)

    print("Waiting for birdwatches to come up...")
    resource_version = ''
    while True:
        print("Waiting for more birdwatches to come up...")
        stream = watch.Watch().stream(crds.list_cluster_custom_object, DOMAIN, "v1alpha1", "birdwatches", resource_version=resource_version)
        for event in stream:
            obj = event["object"]
            operation = event['type']
            spec = obj.get("spec")
            if not spec:
                continue
            metadata = obj.get("metadata")
            resource_version = metadata['resourceVersion']
            name = metadata['name']
            print("Handling %s on %s" % (operation, name))
            done = spec.get("review", False)
            if done:
                continue
            update_virtualservice(crds, obj)
