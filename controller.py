import json
import yaml
from kubernetes import client, config, watch
import os, time
import requests
import monkeypatches.monkeypatch

DOMAIN = "otomato.link"
PROM_URL = os.getenv("PROMETHEUS_URL", "http://prometheus.159.8.233.5.nip.io")  # http://prometheus.default.svc.cluster.local"

def check_canary_health(metric, healthy, deviation):
    print("Checking canary health ")
    current = retrieve_metric(metric)
    if int(current) - int(healthy) > deviation:
        return False
    time.sleep(1)
    return True

def retrieve_metric(query):
    response = requests.get(PROM_URL+"/api/v1/query?query="+query).content
    metric = json.loads(response)
    if metric["data"]["result"]:
        print(metric["data"]["result"][0]["value"][1])
        return metric["data"]["result"][0]["value"][1]
    print(metric)
    return 0

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
    destination_rule = cleanup_k8s_object(destination_rule)
    crds.patch_namespaced_custom_object("networking.istio.io", 
                                        "v1alpha3", 
                                        namespace, 
                                        "destinationrules", 
                                        name, 
                                        destination_rule)
    return destination_rule
         
def cleanup_k8s_object(obj):
    if 'annotations' in obj["metadata"]:
        obj["metadata"].pop("annotations")
    if 'resourceVersion' in obj["metadata"]:
        obj["metadata"].pop("resourceVersion")    
    if 'uid' in obj["metadata"]:
        obj["metadata"].pop("uid")
    if 'selfLink' in obj["metadata"]:    
        obj["metadata"].pop("selfLink")
    return obj

def update_virtualservice(crds, obj):
    metadata = obj.get("metadata")
    if not metadata:
        print("No metadata in object, skipping: %s" % json.dumps(obj, indent=1))
        return
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    obj["spec"]["inprocess"] = True
    service = obj["spec"]["service"]
    metric = obj["spec"]["metric"]
    
    if 'deviation' in obj["spec"]:
        deviation = int(obj["spec"]["deviation"])
    else:
        deviation = 10
    
    if 'if_unhealthy' in obj["spec"]:
        if_unhealthy = obj["spec"]["if_unhealthy"]
    else:
        if_unhealthy = 'rollback'

    if 'increment' in obj["spec"]:
        increment = int(obj["spec"]['increment'])
    else:
        increment = 1

    healthy = retrieve_metric(metric)
    print("Updating: %s" % name)
    canary_healthy = True
    prodWeight = 100
    canaryWeight = 0
    
    destination_rule = update_destination_rule(crds, namespace, service)

    vs = crds.get_namespaced_custom_object("networking.istio.io", "v1alpha3", namespace, "virtualservices", service)
    canary_index = next((index for (index, d) in enumerate(vs["spec"]["http"][0]["route"]) 
                                                                if d["destination"]["subset"] == "canary"), None)
    prod_index = next((index for (index, d) in enumerate(vs["spec"]["http"][0]["route"]) 
                                                                if d["destination"]["subset"] == "production"), None)
    vs = cleanup_k8s_object(vs)
    
    
    while canary_healthy and canaryWeight <=100:
        print("canary %s prod %s " %(canaryWeight, prodWeight))
        vs["spec"]["http"][0]["route"][canary_index]["weight"] = canaryWeight
        vs["spec"]["http"][0]["route"][prod_index]["weight"] = prodWeight
        crds.patch_namespaced_custom_object("networking.istio.io", "v1alpha3", namespace, "virtualservices", name, vs)
        canary_healthy = check_canary_health(metric, healthy, deviation)
        prodWeight-=increment
        canaryWeight+=increment
    
    if canaryWeight >= 100:
        release_canary(destination_rule, vs, crds, obj)
    else:
        exec(if_unhealthy+'(crds, vs, namespace, name)')
  
def freeze(crds, vs, namespace, name):
    print("Freezing the canary")
    return True

def rollback(crds, virtualservice, namespace, name):
    print("Rolling back")
    canary_index = next((index for (index, d) in enumerate(virtualservice["spec"]["http"][0]["route"]) 
                                                                if d["destination"]["subset"] == "canary"), None)
    prod_index = next((index for (index, d) in enumerate(virtualservice["spec"]["http"][0]["route"]) 
                                                                if d["destination"]["subset"] == "production"), None)
    virtualservice["spec"]["http"][0]["route"][canary_index]["weight"] = 0
    virtualservice["spec"]["http"][0]["route"][prod_index]["weight"] = 100
    crds.patch_namespaced_custom_object("networking.istio.io", 
                                        "v1alpha3", 
                                        namespace, 
                                        "virtualservices", 
                                        name, 
                                        virtualservice)


def release_canary(destination_rule, virtualservice, crds, obj):
    #in destinationrule - make prod point at canary
    #update destination rule
    prod_index = next((index for (index, d) in enumerate(destination_rule["spec"]["subsets"]) 
                                                                if d["name"] == "production"), None)
    destination_rule["spec"]["subsets"][prod_index]["labels"]["version"] = obj["spec"]["canary_version"]
    crds.patch_namespaced_custom_object("networking.istio.io", 
                                        "v1alpha3", 
                                        obj["metadata"]["namespace"], 
                                        "destinationrules", 
                                        obj["metadata"]["name"], 
                                        destination_rule)
    #in virtualservice - set weights: prod=100 and canary=0
    rollback(crds, virtualservice, obj["metadata"]["namespace"], obj["metadata"]["name"])
    #now delete the CR
    crds.delete_namespaced_custom_object(DOMAIN, 
                                         "v1alpha1", 
                                         obj["metadata"]["namespace"], 
                                         "birdwatches", 
                                         obj["metadata"]["name"],
                                         {})
         
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
            if operation == "DELETED":
                continue
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
