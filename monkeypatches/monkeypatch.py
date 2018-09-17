
#patch for endpoints
from kubernetes.client.models.v1_endpoints import V1Endpoints 
def set_subsets(self, subsets):
    if subsets is None:
         subsets = [] 
    self._subsets = subsets 

setattr(V1Endpoints, 'subsets', property(fget=V1Endpoints.subsets.fget, fset=set_subsets))

from kubernetes.client.models.v1beta1_custom_resource_definition_status import V1beta1CustomResourceDefinitionStatus 
#patch for customresource conditions
def conditions(self, conditions):
    if conditions is None:
        conditions = []
    self._conditions = conditions

setattr(V1beta1CustomResourceDefinitionStatus, 'conditions', 
        property(fget=V1beta1CustomResourceDefinitionStatus.conditions.fget, fset=conditions))
#patch for customresource stored_versions
def stored_versions(self, stored_versions):
    if stored_versions is None:
        stored_versions = []
    self._stored_versions = stored_versions

setattr(V1beta1CustomResourceDefinitionStatus, 'stored_versions', 
        property(fget=V1beta1CustomResourceDefinitionStatus.stored_versions.fget, fset=stored_versions))
   
#patch kub_config for Python3 and JWT
from kubernetes.config.kube_config import KubeConfigLoader, _is_expired
from six import PY3
import json, base64, datetime
from kubernetes.config.dateutil import UTC, format_rfc3339, parse_rfc3339
def _load_oid_token(self, provider):
    if 'config' not in provider:
        return

    parts = provider['config']['id-token'].split('.')

    if len(parts) != 3:  # Not a valid JWT
        return None
    
    padding = (4 - len(parts[1]) % 4) * '='
    if PY3:
        jwt_attributes = json.loads(
                base64.b64decode(parts[1] + padding).decode('utf-8')
        )
    else:
        jwt_attributes = json.loads(
            base64.b64decode(parts[1] + padding)
        )

    expire = jwt_attributes.get('exp')

    if ((expire is not None) and
        (_is_expired(datetime.datetime.fromtimestamp(expire,
                                                        tz=UTC)))):
        self._refresh_oidc(provider)

        if self._config_persister:
            self._config_persister(self._config.value)

    self.token = "Bearer %s" % provider['config']['id-token']

    return self.token

KubeConfigLoader._load_oid_token = _load_oid_token
