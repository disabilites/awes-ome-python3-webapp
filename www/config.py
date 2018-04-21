import config_default

class Dict(dict):
    '''
    Simple dict but support access as x.y style.
    '''
    def __init__(self, names=(), values=(), **kw):
        super(Dict, self).__init__(**kw)    #调用父类dict的__init__()方法
        for k, v in zip(names, values):     #zip()将names和values中的元素打包成一个个元组，然后返回有这些元组组成的列表。
            self[k] = v

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Dict' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

def merge(defaults, override):     #合并配置文件
    r = {}
    for k, v in defaults.items():
        if k in override:                       #判断override中是否存在k
            if isinstance(v, dict):             #判断v是否是字典类型
                r[k] = merge(v, override[k])
            else:
                r[k] = override[k]              #用overridr中的值替换r中的值
        else:
            r[k] = v
    return r

def toDict(d):
    D = Dict()
    for k, v in d.items():
        #使用三目运算符，如果值是一个dict递归将其转换为Dict再赋值，否则直接赋值
        D[k] = toDict(v) if isinstance(v, dict) else v
    return D

configs = config_default.configs

try:
    import config_override
    configs = merge(configs, config_override.configs)
except ImportError:
    pass

configs = toDict(configs)