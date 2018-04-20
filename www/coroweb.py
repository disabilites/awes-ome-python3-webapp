import asyncio, os, inspect, logging, functools

from urllib import parse

from aiohttp import web

from apis import APIError

def get(path):
    '''
    Define decorator @get('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator
'''
    inspect模块用于解析函数的参数
    inspect.signature().parameters  可以获取函数的所有参数
    通过循环 params.items(),可以获得参数名和其值
    KEYWORD_ONLY判断是否是命名关键字参数
'''

#收集没有默认值的命名关键字参数
def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

#获取命名关键字参数
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

#判断有没有命名关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

#判断有没有关键字参数
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

#判断是否含有名叫'request'参数，且该参数是否为最后一个参数
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found

class RequestHandler(object):

    # 初始化，接受app参数
    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    #构造协成
    async def __call__(self, request):
        kw = None
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST':        #判断客户端发来的方法是否为POST
                if not request.content_type:    #查询有没提交数据的格式（EncType）
                    return web.HTTPBadRequest(text='Missing Content-Type.')
                ct = request.content_type.lower()   #转化为小写
                if ct.startswith('application/json'):   # startswith()方法用于检查字符串，测请求内容是否是以'application/json'开头，如果是则返回True
                    params = await request.json()         #将请求内容解码为Json格式
                    if not isinstance(params, dict):      #如果params不是字典类型
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    kw = dict(**params)     #创建并返回一个字典
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':     #判断客户端发来的方法是否为GET
                qs = request.query_string    #URL中的查询字符串
                if qs:                       #如果查询字符串存在
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():   #parse.parse_qs(qs, True)将URL查询字符串中的键值组成字典并返回
                        kw[k] = v[0]
        if kw is None:  #如果没有查询字符串，则返回匹配信息
            kw = dict(**request.match_info)
        else:
            if not self._has_var_kw_arg and self._named_kw_args:
                # 当函数参数没有关键字参数时，移去request除命名关键字参数所有的参数信息
                copy = dict()
                for name in self._named_kw_args:    #循环命名关键字参数
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg:
            for k, v in request.match_info.items():    #检查命名关键参数
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        if self._has_request_arg:
            kw['request'] = request
        if self._required_kw_args:  #假如命名关键字参数(没有附加默认值)，request没有提供相应的数值，报错
            for name in self._required_kw_args:     #检测缺少的参数
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:   #APIError另外创建
            return dict(error=e.error, data=e.data, message=e.message)

def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

#编写一个add_route函数，用来注册一个URL处理函数
def add_route(app, fn):
    method = getattr(fn, '__method__', None)        #getattr() 函数用于返回一个对象属性值。
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):     #iscoroutinefunction()应该是判断是否是协程；isgeneratorfunction()应该是判断是否是生成器
        fn = asyncio.coroutine(fn)                                                       #将fn标记为coroutine类型
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method, path, RequestHandler(app, fn))

#直接导入文件，批量注册一个URL处理函数
def add_routes(app, module_name):
    n = module_name.rfind('.')      #rfind() 返回字符串最后一次出现的位置(从右向左查询)，如果没有匹配项则返回-1。
    if n == (-1):
        mod = __import__(module_name, globals(), locals())  #__import__() 函数用于动态加载类和函数 。如果一个模块经常变化就可以使用 __import__() 来动态载入。
    else:
        name = module_name[n+1:]        #获取“.”后面的字符串
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    for attr in dir(mod):               #dir()返回mod的属性、方法列表
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr)     #返回fn的attr属性
        if callable(fn):            #callable()用于检查一个对象是否可调用。返回True有可能失败，返回False绝对不会成功
            method = getattr(fn, '__method__', None)    #获取'__method__'的值
            path = getattr(fn, '__route__', None)       #获取'__route__'的值
            if method and path:         #这里要查询path以及method是否存在而不是等待add_route函数查询，因为那里错误就要报错了
                add_route(app, fn)