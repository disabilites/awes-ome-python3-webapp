_author_ = 'horizon'

import logging,asyncio

import aiomysql

def log(sql,args=()):
    logging.info('SQL: %s'% sql)


async def create_pool(loop,**kw):
    logging.info('create database connection pool...')
    global __pool
    __pool = await aiomysql.create_pool(
        host=kw.get('host','localhost'),   #服务器地址
        port=kw.get('port','3306'),        #服务器端口号
        user=kw['user'],                    #用户名
        password=kw['password'],           #密码
        db=kw['db'],                        #数据库名称
        charset=kw.get('charset','utf8'),   #连接编码
        autocommit=kw.get('autocommit',True),
        maxsize=kw.get('maxsize',10),
        minsize=kw.get('minsize',1),
        loop=loop
    )


async def select(sql,args,size=None):
    log(sql,args)
    global __pool
    with(await __pool) as conn:
        cur = await conn.cursor(aiomysql.DictCursor)
        await  cur.execute(sql.replace('?','%s'),args or ())
        if size:
            rs = await cur.fetchmany(size)   #fetchmant()可以获取表中的数据
        else:
            rs = await cur.fetchall()
        await cur.close()
        logging.info('rows returned:%s'% len(rs))
        return rs


async  def execute(sql,args,autocommit=True):
    log(sql)
    with(await __pool) as conn:
        try:
            cur = await conn.cursor()
            await cur.execute(sql.replace('?','%s'),args)
            affected = cur.rowcount
            await cur.close()
        except BaseException as e:
            raise
        return affected

def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ','.join(L)  #join()返回一个以“,”作为分隔符的连接各个元素后生产的字符串

class Field(object):

    def __init__(self,name,column_type,primary_key,default):
        self.name = name                #列名
        self.column_type = column_type  #数据类型
        self.primary_key = primary_key  #是否主键
        self.default = default          #默认值

    def __str__(self):
        return '<%s,%s:%s>' % (self.__class__.__name__,self.column_type,self.name)

class StringField(Field):

    def __init__(self,name=None,default=False,primary_key=False,ddl='varchar(100)'):
        super().__init__(name,ddl,primary_key,default)

class BooleanField(Field):

    def __init__(self,name=None,default=False):
        super().__init__(name,'boolean',False,default)

class IntegerField(Field):

    def __init__(self,name=None,primary_key=False,default=0):
        super().__init__(name,'bigint',primary_key,default)

class FloatField(Field):

    def __init__(self,name=None,primary_key=False,default=0.0):
        super().__init__(name,'real',primary_key,default)

class TextField(Field):

    def __init__(self,name=None,default=None):
        super().__init__(name,'text',False,default)

class ModelMetaclass(type):

    # 如果是基类对象，则不做处理
    def __new__(cls, name, bases, attrs):
        if name == 'Model':
            return type.__new__(cls,name,bases,attrs)
        # 保存表名，如果获取不到表名，则把类名当作表名（利用了or短路原理）
        tableNmae = attrs.get('__table__',None) or name
        logging.info('found model：%s (table：%s)' % (name,tableNmae))
        mappings = dict()       #保存列类型的对象
        fields = []              #保存列名的数组
        primarykey = None       #主键
        for k,v in attrs.items():
            #如果是列名就保存
            if isinstance(v,Field):
                logging.info('  found mapping：%s ==> %s' % (k,v))
                mappings[k] = v
                if v.primary_key:
                    #找到主键
                    if primarykey:
                        raise RuntimeError('Duplicate primary key for field: %s' % k)
                    primarykey = k
                else:
                    fields.append(k)        #保存非主键列名

        if not primarykey:
            raise RuntimeError('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f:'‘%s’' % f,fields))
        attrs['__mappings__'] = mappings        #保存属性和列的映射关系
        attrs['__tableName__'] = tableNmae      #表名
        attrs['__primary_key'] = primarykey     #主键属性名
        attrs['__fields__'] = fields            #除主键外的属性名
        #保存了增删改查四种方法，``避免与SQL关键字冲突
        attrs['__select__'] = 'select `%s`,%s from `%s`' % (primarykey,','.join(escaped_fields),tableNmae)
        attrs['__insert__'] = 'insert into `%s` (%s,`%s`) values (%s)' % (tableNmae,','.join(escaped_fields),primarykey,create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=? ' % (tableNmae,','.join(map(lambda  f: '`%s` = ?' % (mappings.get(f).name or f),fields)),primarykey)
        attrs['__delete__'] = 'delete from `%s` where `%s` = ?' % (tableNmae,primarykey)
        return  type.__new__(cls,name,bases,attrs)

#这是模型的基类,继承于dict,主要作用就是如果通过点语法来访问对象的属性获取不到的话,可以定制__getattr__来通过key来再次获取字典里的值
class Model(dict,metaclass=ModelMetaclass):

    def __init__(self,**kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
         try:
             return self[key]
         except KeyError:
             raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self,key):
        return getattr(self,key,None)

    def getValueOrDefault(self,key):
        value = getattr(self,key,None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s：%s' % (key,str(value)))
                setattr(self,key,value)
        return value

    @classmethod
    # 获取表里符合条件的所有数据,类方法的第一个参数为该类名
    async def findAll(cls,where=None,args=None,**kw):
        'find object by where clause.'
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy',None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit',int)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit,int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit,tuple) and len(limit) == 2:
                sql.append('?,?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value：%s' % str(limit))
            rs = await select(''.join(sql),args)
            return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls,selectField,where=None,args=None):
        ' find number by select and where.'
        sql = ['select %s _num_from `%s`' % (selectField,cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(''.join(sql),args,1)
        if len(rs) == 0:
            return  None
        return rs[0]['_num_']

    @classmethod
    async def find(cls,pk):
        'find object by primary key.'
        rs = await select('%s where `%s` = ?' % (cls.__select__,cls.primarykey),[pk],1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    async def save(self):
        args = list(map(self.getValueOrDefault,self.__field__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__,args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    async  def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__deletc__,args)
        if rows != 1:
            logging.warn('failed to remove by primay key：affected rows：%s' %rows)


#以下为测试
loop = asyncio.get_event_loop()
loop.run_until_complete(create_pool(host='127.0.0.1', port=3306,user='root', password='cx19980225',db='user', loop=loop))
rs = loop.run_until_complete(select('select * from User',None))
#获取到了数据库返回的数据
print("heh:%s" % rs)