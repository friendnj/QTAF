# -*- coding: utf-8 -*-
'''配置接口

一、配置格式
配置文件名默认为settings.py，可以通过环境变量指定用户配置文件的路径
qtaf相关配置的环境变量为：
QTAF_EXLIB_PATH: 指定exlib的路径，exlib下放置对应的qtaf、qt4s、installed_libs.txt等文件
QTAF_INSTALLED_LIBS: 指定已经安装的库的列表，以分号分隔，例如qt4s，用来代替不使用installed_libs.txt的场景
QTAF_SETTINGS_MODULE: 指定用户自定义的配置文件的路径，最后加载，会覆盖已经存在的配置

配置变量名必须符合pyton变量名规范，且统一使用大写，且不可以以"__"开头

如：
CONFIG_OPTION = True
DEBUG = True
RUNNER_THREAD_CNT = 5
BANNER = "hello"

二、使用示例：
from testbase.conf import settings
print settings.CONFIG_OPTION

注意 settings的值都是只读的，不可以修改，如果尝试修改会导致异常

三、配置优先级
配置存在2个优先级，当存在名字冲突时，使用高优先级的配置的值。优先级自低到高分别为：
1、QTAF配置                     固定为：test_proj/exlib/qtaf.egg/qtaf_settings.py
2、lib配置                      已经配置在test_proj/exlib/installed_libs.txt的包中的settings模块
3、用户自定义配置          固定为：test_proj/settings.py
'''

#2015/03/18 eeelin 新建
#2015/03/19 eeelin 简化代码结构
#2015/10/30 eeelin 支持加载lib的默认配置文件

import os
import sys
import imp
import qtaf_settings
from testbase.exlib import ExLibManager

_DEFAULT_SETTINSG_MODULE = "settings"
    
class _Settings(object):
    '''配置读取接口
    '''
    def __init__(self):
        self.__sealed = False
        self._load()
        self.__sealed = True
        
    def _load(self):
        '''加载配置
        :returns: Settings - 设置读取接口
        '''    
        #先加载一次项目配置
        try:
            pre_settings = self._load_proj_settings_module("testbase.conf.pre_settings")
        except ImportError:  #非测试项目情况下使用没有项目settings.py
            pre_settings = None
        
        mode = getattr(pre_settings, "PROJECT_MODE", getattr(qtaf_settings, 'PROJECT_MODE', None))
        
        #加载扩展库或应用配置
        if mode == "standard": #Python标准模式
            installed_apps = getattr(pre_settings, "INSTALLED_APPS",  getattr(qtaf_settings, 'INSTALLED_APPS', []))
            
        else: #独立模式
            proj_root = self._get_standalone_project_root(pre_settings)
            installed_apps = ExLibManager(proj_root).list_names()
            
        #优先加载QTAF设置
        self._load_setting_from_module(qtaf_settings)
        
        for appname in installed_apps:
            modname = "%s.settings" % appname
            try:
                __import__(modname)
            except ImportError:
                pass
            else:
                self._load_setting_from_module(sys.modules[modname])
                
        #加载用户自定义设置 
        try:
            proj_settings = self._load_proj_settings_module("testbase.conf.settings")
        except ImportError: #非测试项目情况下使用没有项目settings.py
            pass
        else:
            self._load_setting_from_module(proj_settings)
        
        #非标准模式下需要设置项目根目录，标准模式要求项目在settings中显式设置
        if mode != "standard":
            self.PROJECT_ROOT = proj_root
            self.INSTALLED_APPS = ExLibManager(proj_root).list_names()
        
    def _load_proj_settings_module(self, import_name ):
        '''加载项目配置文件
        '''
        user_settings = os.environ.get("QTAF_SETTINGS_MODULE", None)
        if user_settings:
            parts = user_settings.split('.')
            parts_temp = parts[:]
            dir_path = None
            while parts_temp:
                if dir_path:
                    fd, dir_path, desc = imp.find_module(parts_temp[0], [dir_path])
                else:
                    fd, dir_path, desc = imp.find_module(parts_temp[0])
                del parts_temp[0]
        else:
            fd, dir_path, desc = imp.find_module(_DEFAULT_SETTINSG_MODULE)
        return imp.load_module(import_name, fd, dir_path, desc)
    
    def _load_setting_from_module(self, module ):
        '''从模块中加载设置
        '''
        for name in dir(module):
            if name.startswith('__'):
                continue
            if name.islower():
                continue
            setattr(self, name, getattr(module,name))

    def _get_standalone_project_root(self, pre_settings):
        '''获取独立模式下的项目的根目录
        '''
        proj_root = getattr(pre_settings, "PROJECT_ROOT", None)
        if proj_root:
            return proj_root
        if os.path.isfile(__file__): #没使用qtaf.egg包
            pwd=os.getcwd()
            #使用外链或拷贝文件的方式
            dst_path=os.path.realpath(os.path.join(os.path.dirname(__file__), '..'))
            if pwd.find(dst_path)>=0:
                return dst_path
            
            #eclipse调试使用工程引用的方式
            if not os.environ.has_key('PYTHONPATH'):
                return pwd
            py_paths=os.environ['PYTHONPATH']
            paths=py_paths.split(";")
            if len(paths)>2:
                dst_path=paths[1]
            if pwd.find(dst_path)>=0:
                return dst_path
            
            #非预期的情况，返回当前工作目录
            return pwd
        else: #使用的egg包，qtaf.egg包在exlib目录中
            qtaf_top_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), '..'))
            return os.path.realpath(os.path.join(qtaf_top_dir, '..', '..'))
        
    def get(self, name, *default_value ):
        '''获取配置
        '''
        if len(default_value) > 1:
            raise TypeError("get expected at most 3 arguments, got %s"%(len(default_value)+2))
        if default_value:
            return getattr(self, name, default_value[0])
        else:
            return getattr(self, name)
        
    def __setattr__(self, name, value ):
        if not name.startswith('_Settings__') and self.__sealed:
            raise RuntimeError("尝试动态修改配置项\"%s\""%name)
        else:
            super(_Settings,self).__setattr__(name, value)
                
    def __getattribute__(self, name):#加上这个是为了使pydev不显示红叉
        return super(_Settings,self).__getattribute__(name)
           
    def __iter__(self):
        for name in dir(self):
            if not name.startswith('__') and name.isupper():
                yield name
                
settings = _Settings()