from flask import current_app as capp
from eve.utils import home_link
from .labels import LABELS
import re


def get_cfg():
    """
    Will get all necessary data out of the eve-app.
    It reads 'SERVER_NAME', 'API_NAME', 'BLUEPRINT_DOCUMENTATION' and
        'DOMAIN' out of app.config as well as app.url_map

    The Hirarchy of Information is:
    1. list all endpoints from url_map
    2. add data out of BLUEPRINT_DOCUMENTATION where additional data is given
    3. update with data out of DOMAIN

    Therefore, if DOMAIN may overrite documentation from
    BLUEPRINT_DOCUMENTATION, but in general blueprints are not described
    in DOMAIN, which is why we introduced this extra dict-item.

    :returns: dict with 'base', 'server_name', 'api_name', 'domains'
    """
    cfg = {}
    base = home_link()['href']
    if '://' not in base:
        protocol = capp.config['PREFERRED_URL_SCHEME']
        print(base)
        base = '{0}://{1}'.format(protocol, base)

    cfg['base'] = base
    cfg['server_name'] = capp.config['SERVER_NAME']
    cfg['api_name'] = capp.config.get('API_NAME', 'API')
    cfg['domains'] = {}
    if capp.config.get('BLUEPRINT_DOCUMENTATION') is not None:
        cfg['domains'] = parse_map(capp.url_map, capp.config)
        for domain in cfg['domains'].keys():
            cfg['domains'][domain]['description'] = \
                capp.config['BLUEPRINT_DOCUMENTATION'].get(domain, {})
    doku = {}
    for domain, resource in list(capp.config['DOMAIN'].items()):
        if (resource['item_methods'] or resource['resource_methods']) \
                and not resource['internal_resource']:
            # hide the shadow collection for document versioning
            if 'VERSIONS' not in capp.config or not \
                    domain.endswith(capp.config['VERSIONS']):
                doku[domain] = endpoint_definition(domain, resource)
    cfg['domains'].update(doku)
    return cfg


def parse_map(url_map, config):
    """
    will extract information out of the url_map and provide them in a dict-form
    :param url_map: an url_map in the format like app.url_map from eve
    :param config: the app.config dict from the eve-app the url_map belongs to
    :returns: empty dict if url-endpoints with methods
    """
    ret = {}
    for rule in url_map.iter_rules():
        line = str(rule)
        # first part if the rule specifies the endpoint
        # between the first two '/' is the resource
        resource = line.split("/")[1]
        # the endpoint is described by a regex, but we want only the name
        path = re.sub(r'<(?:[^>]+:)?([^>]+)>', '{\\1}', line)
        if resource not in ret:
            # this is the first path of this resource, create dict-entry
            ret[resource] = {'paths': {}, 'description': {}}
        # add path to dict
        ret[resource]['paths'][path] = {}
        for method in rule.methods:
            if method in ['GET', 'POST', 'PATCH', 'PUT', 'DELETE']:
                # we only display these methods, other HTTP-Methods don't need
                # documentation
                ret[resource]['paths'][path][method] = {}

            doc = config['BLUEPRINT_DOCUMENTATION'].get(resource)
            doc_schema = None
            if doc is not None:
                doc_schema = doc.get('schema')
            if (method in ['POST', 'PATCH', 'PUT'])\
                    and (doc_schema is not None):
                ret[resource]['paths'][path][method]['params'] = \
                    schema(config['DOMAIN'][doc_schema])
    return ret


def identifier(resource):
    name = resource['item_lookup_field']
    ret = {
        'name': name,
        'type': 'string',
        'required': True,
    }
    return ret


def schema(resource, field=None):
    """
    extracts the detailed cerberus-schema of this endpoint
    :param resource: the resource of the endpoint
    :param field: the field for which the schema will be returned.
        If no field specified, return a dict for all fields of the endpoint
    :returns: schema as dict
    """
    ret = []
    if field is not None:
        params = {field: resource['schema'][field]}
    else:
        params = resource['schema']
    for field, attrs in list(params.items()):
        template = {
            'name': field,
            'type': 'None',
            'required': False,
        }
        template.update(attrs)
        ret.append(template)
        # If the field defines a schema, add any fields from the nested
        # schema prefixed by the field name
        if 'schema' in attrs and all(isinstance(v, dict)
                                     for v in list(attrs['schema'].values())):
            for subfield in schema(attrs):
                subfield['name'] = field + '.' + subfield['name']
                ret.append(subfield)
        # If the field defines a key schema, add any fields from the nested
        # schema prefixed by the field name and a * to denote the wildcard
        if 'keyschema' in attrs:
            attrs['schema'] = attrs.pop('keyschema')
            for subfield in schema(attrs):
                subfield['name'] = field + '.*.' + subfield['name']
                ret.append(subfield)
    return ret


def endpoint_definition(domain, resource):
    """
    gets the documentation of a specified endpoint
    :param domain: the endpoint
    :param resource: the resource-subdict of config['DOMAIN']
    :returns: the documentation as a dict (paths, methods, fields)
    """
    ret = {}
    ret['description'] = resource['description']
    ret['paths'] = paths(domain, resource)
    return ret


def paths(domain, resource):
    """returns the documentation of all endpoints of a domain for which we have
    descriptions in the config
    :param domain: the domain of the endpoints
    :param resource: the resource-subdict of config['DOMAIN']
    :returns: dict with paths and their documentation (methods, fields)
    """
    # resoruce-endpoint
    ret = {}
    path = '/{0}'.format(resource.get('url', domain))
    # we don't care about the refex definition, we want the name of the path
    path = re.sub(r'<(?:[^>]+:)?([^>]+)>', '{\\1}', path)
    pathtype = 'resource'
    ret[path] = methods(domain, resource, pathtype)

    # item-endpoint
    primary = identifier(resource)
    path = '{0}/{1}'.format(path, pathparam(primary['name']))
    pathtype = 'item'
    ret[path] = methods(domain, resource, pathtype)

    alt = resource.get('additional_lookup', None)
    if alt is not None:
        path = '/{0}/{1}'.format(domain, pathparam(alt['field']))
        pathtype = 'additional_lookup'
        ret[path] = methods(domain, resource, pathtype, alt['field'])
    return ret


def methods(domain, resource, pathtype, param=None):
    """
    extracts mathods and descriptions of a sepcified path
    :param domain: the domain of the endpoint
    :param resource: the resource-subdict of config['DOMAIN']
    :param pathtype: String from ('item', 'resource')
    :param param:
    :returns: dict of methods and their documentation (fields)
    """
    ret = {}
    if pathtype == 'additional_lookup':
        method = 'GET'
        ret[method] = {}
        ret[method]['label'] = get_label(domain, pathtype, method)
        ret[method]['params'] = schema(resource, param)
    else:
        key = '{0}_methods'.format(pathtype)
        methods = resource[key]
        for method in methods:
            ret[method] = {}
            ret[method]['label'] = get_label(domain, pathtype, method)
            ret[method]['params'] = []
            if method == 'POST':
                ret[method]['params'].extend(schema(resource))
            elif method == 'PATCH':
                ret[method]['params'].append(identifier(resource))
                ret[method]['params'].extend(schema(resource))
            elif pathtype == 'item':
                ret[method]['params'].append(identifier(resource))
    return ret


def pathparam(param):
    return '{{{0}}}'.format(param)


def get_label(domain, pathtype, method):
    """
    a description of what the method does (e.g. PATCH will upadate an item)
    :param domain: the domain of the endpoint
    :param pathtype: String from ('item', 'resource')
    :param method: the method for this label
    :returns: description as a string
    """
    verb = LABELS[method]
    if method == 'POST' or pathtype != 'resource':
        noun = capp.config['DOMAIN'][domain]['item_title']
        article = 'a'
    else:
        noun = domain
        article = 'all'
    return '{0} {1} {2}'.format(verb, article, noun)
