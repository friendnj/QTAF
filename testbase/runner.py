# -*- coding: utf-8 -*-
'''
TestRunner负责多个测试用例，目前提供三种方式:

    - 单线程执行 TestRunner
    - 多线程执行 ThreadingTestRunner
    - 多进程执行 MultiProcessTestRunner

整个执行逻辑可以用以下伪代码来理解::

    for test in tests:
        report.begin_test(test)
        result = report.get_testresult_factory().create(test)
        report.end_test(test, result)

'''
#2014/10/29    eeelin 创建

import threading
import multiprocessing
import traceback
import collections
import random
import types
import sys
from Queue import Empty
from testbase.loader import TestLoader
from testbase import serialization
from testbase.testcase import TestCase, TestCaseRunner
from testbase.report import ITestReport
from testbase.testresult import TestResultCollection
            
class TestCaseSettings(object):
    '''目标测试用例配置
    '''
    def __init__(self, names=[], excluded_names=[], priorities=None, status=None ):
        '''构造函数
        
        :param names: 测试用例名
        :type names: list
        :param excluded_names: 排除测试用例名
        :type excluded_names: list
        :param priorities: 指定用例优先级，如果不指定则默认全部优先级
        :type priorities: list
        :param status: 指定用例状态，如果不指定则默认全部状态
        :type status: list
        '''
        self.names = list(names)
        self.excluded_names = []
        for it in excluded_names:
            if it:
                self.excluded_names.append(it)
        if priorities is None:
            priorities = [TestCase.EnumPriority.BVT,
                          TestCase.EnumPriority.High,
                          TestCase.EnumPriority.Normal,
                          TestCase.EnumPriority.Low]
        if status is None:
            status = [TestCase.EnumStatus.Design,
                      TestCase.EnumStatus.Implement,
                      TestCase.EnumStatus.Ready,
                      TestCase.EnumStatus.Review,
                      TestCase.EnumStatus.Suspend]
        self.priorities = priorities
        self.status = status

        self.excluded_cls_names = []
        self.excluded_mod_names = []
        for it in self.excluded_names:
            if self._is_test_class(it):
                self.excluded_cls_names.append(it)
            else:
                self.excluded_mod_names.append(it)
                        
    def _is_test_class(self, name ):
        '''判断路径是否是一个类名
        '''
        if '/' in name: #数据驱动相关的类
            return True
        if '.' not in name: #不可能直接引用类名
            return False
        
        try:
            __import__(name)
            return False #为模块
        except ImportError:
            modname, clsname = name.rsplit('.',1)
            try:
                __import__(modname)
                mod = sys.modules[modname]
            except:
                return False #不存在的模块
            else:
                return hasattr(mod, clsname)
            
    def filter(self, testcase ):
        '''测试用例过滤函数
        
        :param testcase: 测试用例
        :type testcase: TestCase
        '''
        name = testcase.test_name
        for it in self.excluded_cls_names:
            if name.startswith(it):
                return "match excluded list: '%s'" % it
        for it in self.excluded_mod_names:
            if name.startswith(it+'.'):
                return "match excluded list: '%s'" % it
        if testcase.status not in self.status:
            return "testcase with status '%s' is excluded" % testcase.status
        if testcase.priority not in self.priorities:
            return "testcase with priority '%s' is excluded" % testcase.priority
        return False
        
class BaseTestRunner(object):
    '''测试执行器基类
    '''
    def __init__(self, report ):
        '''构造函数
        
        :param report: 测试报告
        :type report: ITestReport
        '''
        self.__report = report
        
    @property
    def report(self):
        '''对应的测试报告
        
        :returns: ITestReport
        '''
        return self.__report
        
    def run(self, target ):
        '''运行测试
        
        :param target: 指定要执行的测试用例
        :type target: list/string/TestCaseSettings
        '''
        self.__report.begin_report()
        
        if isinstance(target, str):
            target = TestCaseSettings(names=target.split(" "))
            
        if isinstance(target, TestCaseSettings):
            loader = TestLoader(target.filter)
            filtered_tests = []
            tests = []            
            for it in target.names:
                tests += loader.load(it)
                load_errs = loader.get_last_errors()
                filtered_tests += loader.get_filtered_tests_with_reason().items()
                for testname in load_errs:
                    self.__report.error('Loader', '"%s" load error:%s'%(testname,load_errs[testname]), dict(error_testname=testname, error=load_errs[testname]))
            
            self.__report.info('Loader', 'filter %s testcases totally' % len(filtered_tests), dict(filtered_testcases=filtered_tests))
            self.__report.info("Loader", 'load %s testcases totally' % len(tests), dict(testcases=tests))
        else:
            tests = target

        self.run_all_tests(tests)
        self.__report.end_report()
        
    def run_all_tests(self, tests ):
        '''执行全部的测试用例
        
        :param tests: 测试用例对象列表
        :type tests: list
        '''
        random.shuffle(tests)
        for test in tests:
            self.run_test(test)
        
    def run_test(self, test ):
        '''执行一个测试用例
        
        :param test: 测试用例
        :type test: TestCase
        :returns: boolean - 测试是否通过
        '''
        runner = getattr(test, 'case_runner', TestCaseRunner())
        result = runner.run(test, self.__report.get_testresult_factory())
        if isinstance(result, TestResultCollection):
            self._log_collection_result(result)
        else:
            self.__report.log_test_result(result.testcase, result)
        return result.passed
    
    def _log_collection_result(self, result_collection ):
        '''记录结果集合
        '''
        for it in result_collection:
            if isinstance(it, TestResultCollection):
                self._log_collection_result(it)
            else:
                self.__report.log_test_result(it.testcase, it)
            
        
    
            
class TestRunner(BaseTestRunner):
    '''测试执行器
    '''
    def __init__(self, report, retries=0 ):
        '''构造函数
        
        :param result: 测试报告
        :type result: ITestReport
        :param retries: 用例失败时重试次数
        :type retries: int
        '''
        super(TestRunner, self).__init__(report)
        self._retries = retries

    def run_all_tests(self, tests ):
        '''执行全部的测试用例
        
        :param test: 测试用例对象列表
        :type tests: list
        '''
        random.shuffle(tests)
        tests_queue = collections.deque(tests)
        tests_retry_dict = {}
        while len(tests_queue) > 0:
            test = tests_queue.popleft()
            passed = self.run_test(test)
            if not passed:
                tests_retry_dict.setdefault(test, 0)
                if tests_retry_dict[test] < self._retries:
                    tests_retry_dict[test] += 1
                    tests_queue.append(test)
                    
                    
class ThreadSafetyReport(ITestReport):
    '''TestReport修饰器，保证线程安全
    '''
    def __init__(self, report ):
        '''构造函数
        
        :param result: 测试报告
        :type result: ITestReport
        '''
        self._lock = threading.Lock()
        self._report = report
        
    def begin_report(self):
        '''开始测试执行
        '''
        with self._lock:
            return self._report.begin_report()
    
    def end_report(self):
        '''结束测试执行
        
        :param passed: 测试是否通过
        :type passed: boolean
        '''
        with self._lock:
            return self._report.end_report()
    
    def log_test_result(self, testcase, testresult ):
        '''记录一个测试结果
        
        :param testcase: 测试用例
        :type testcase: TestCase
        :param testresult: 测试结果
        :type testresult: TestResult
        '''
        with self._lock:
            return self._report.log_test_result(testcase, testresult)
    
    def get_testresult_factory(self):
        '''获取对应的TestResult工厂
        
        :returns: ITestResultFactory
        '''
        with self._lock:
            return self._report.get_testresult_factory()
    
    def log_record(self, level, tag, msg, record):
        '''增加一个记录
        
        :param level: 日志级别
        :param msg: 日志消息
        :param tag: 日志标签
        :param record: 日志记录信息
        :type level: string
        :type tag: string
        :type msg: string
        :type record: dict
        '''
        with self._lock:
            return self._report.log_record(level, tag, msg, record)
    
class ThreadingTestRunner(BaseTestRunner):
    '''使用多线程并发执行用例
    '''
    def __init__(self, report, thread_cnt=5, retries=0 ):
        '''构造函数
        
        :param report: 测试报告
        :type report: ITestReport
        :param thread_cnt: 线程数
        :type thread_cnt: int
        :param retries: 用例失败时重试次数
        :type retries: int
        '''
        self._thread_cnt = int(thread_cnt)
        self._retries = retries
        self._lock = threading.Lock()
        if thread_cnt > 1:
            report = ThreadSafetyReport(report)
        super(ThreadingTestRunner, self).__init__(report)
        
    def run_all_tests(self, tests ):
        '''执行全部的测试用例
        
        :param test: 测试用例对象列表
        :type tests: list
        '''
        random.shuffle(tests)
        tests_queue = collections.deque(tests)
        tests_retry_dict = {}
        threads = []
        for _ in range(self._thread_cnt):
            thread = threading.Thread(target=self._run_test_from_queue, args=(tests_queue, tests_retry_dict))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
                
    def _run_test_from_queue(self, tests_queue, tests_retry_dict):
        '''从队列中不断取用例并执行
        
        :param tests_queue: 测试用例队列
        :type tests_queue: deque
        :param tests_retry_dict: 测试用例重跑记录
        :type tests_retry_dict: dict
        '''
        while len(tests_queue)>0 :            
            with self._lock:
                if len(tests_queue)<=0:
                    break
                test = tests_queue.pop()
            passed = self.run_test(test)
            with self._lock:    
                if not passed:
                    tests_retry_dict.setdefault(test, 0)
                    if tests_retry_dict[test] < self._retries:
                        tests_retry_dict[test] += 1
                        tests_queue.append(test)


class EnumProcessMsgType(object):
    '''多进程间通信用的消息类型
    '''
    Worker_Quit = 0
    Worker_RunTest = 1
    Worker_Idle = 2
    Worker_Error = 3

    Result_GetAttr = 4
    Result_AttrValue = 5
    Result_AttrError = 6
    Result_Func = 7
    Result_CallFunc = 8
    Result_Return = 9
    Result_Raise = 10
    
    Report_LogTestResult = 12
    Report_LogRecord = 13
    
class TestResultFunctionProxy(object):
    '''测试结果函数代理
    '''
    def __init__(self, from_worker, obj_id, func_name):
        '''构造函数
        
        :param from_worker: 所属的工作者
        :type from_worker: TestWorker
        :param obj_id: 对象ID
        :type obj_id: int
        :param func_name: 函数名
        :type func_name: string
        '''
        self._worker = from_worker
        self._objid = obj_id
        self._func_name = func_name        
        
    def __call__(self, *args, **kwargs ):
        self._worker.send_message((EnumProcessMsgType.Result_CallFunc, self._objid, self._func_name,
                                   args, kwargs))
        msg = self._worker.recv_message(5)
        msg_type = msg[0]
        if msg_type == EnumProcessMsgType.Result_Return:
            return msg[1]
        elif msg_type == EnumProcessMsgType.Result_Raise:
            raise RuntimeError(str(msg[1]))
        else:
            raise RuntimeError("unexpect message: %s" % msg)
        
class TestResultProxy(object):
    '''测试结果代理
    '''
    def __init__(self, from_worker, obj_id, passed ):
        '''构造函数
        
        :param from_worker: 来源的工作者
        :type from_worker: TestWorker
        :param obj_id: 对象ID
        :type obj_id: int
        :param passed: 测试是否通过
        :type passed: boolean
        :param rpc_tx: 测试结果代理RPC请求发送端
        :type rpc_tx: multiprocessing.Queue
        :param rpc_rx: 测试结果代理RPC结果接收端
        :type rpc_rx: multiprocessing.Queue
        '''
        self.__worker = from_worker
        self.__passed = passed
        self.__objid = obj_id

    def __getattr__(self, name ):
        if name.startswith('_TestResultProxy__'):
            return super(TestResultProxy,self).__getattr__(name)
        if name == 'passed': #shortcut
            return self.__passed
        self.__worker.send_message((EnumProcessMsgType.Result_GetAttr, self.__objid, name))
        msg = self.__worker.recv_message(5)
        msg_type = msg[0]
        if msg_type == EnumProcessMsgType.Result_AttrValue:
            return msg[1]
        elif msg_type == EnumProcessMsgType.Result_Func:
            return TestResultFunctionProxy(self.__worker, self.__objid, name)
        elif EnumProcessMsgType.Result_AttrError:
            raise AttributeError(msg[1])
        else:
            raise RuntimeError("unexpect message: %s" % msg)
        
    def __setattr__(self, name, value ):
        if name.startswith('_TestResultProxy__'):
            super(TestResultProxy,self).__setattr__(name, value)
        else:
            raise RuntimeError("read only")
        
class TestReportProxy(ITestReport):
    '''测试报告代理
    '''
    def __init__(self, worker_id, ctrl_msg_queue, result_factory, result_manager ):
        '''构造函数
        
        :param worker_id: 工作者ID
        :type worker_id: string
        :param ctrl_msg_queue: 控制进程的消息队列
        :type ctrl_msg_queue: multiprocessing.Queue
        :param result_factory: 测试结果工厂
        :type result_factory: ITestResultFactory
        :param result_manager: 测试结果残根管理器
        :type result_manager：TestResultStubManager
        '''
        self._worker_id = worker_id
        self._ctrl_msg_queue = ctrl_msg_queue
        self._result_factory = result_factory
        self._result_manager = result_manager
            
    def begin_report(self):
        '''开始测试执行
        '''
        raise RuntimeError("should not call this")
    
    def end_report(self):
        '''结束测试执行
        
        :param passed: 测试是否通过
        :type passed: boolean
        '''
        raise RuntimeError("should not call this")
        
    def log_test_result(self, testcase, testresult ):
        '''记录一个测试结果
        
        :param testcase: 测试用例
        :type testcase: TestCase
        :param testresult: 测试结果
        :type testresult: TestResult
        '''
        objid = self._result_manager.add_result(testresult)
        self._ctrl_msg_queue.put((EnumProcessMsgType.Report_LogTestResult, 
                                  self._worker_id, serialization.dumps(testcase), objid, testresult.passed))
    
    def log_record(self, level, tag, msg, record):
        '''增加一个记录
        
        :param level: 日志级别
        :param tag: 日志标签
        :param msg: 日志消息
        :param record: 日志记录信息
        :type level: string
        :type tag: string
        :type msg: string
        :type record: dict
        '''
        self._ctrl_msg_queue.put((EnumProcessMsgType.Report_LogRecord, (level, tag, msg, record)))
    
    def get_testresult_factory(self):
        '''获取对应的TestResult工厂
        
        :returns: ITestResultFactory
        '''
        return self._result_factory
    
    
class _EmptyClass(object):
    pass


    
class TestResultStubManager(object):
    '''测试结果残根管理器
    '''
    def __init__(self, rsp_queue ):
        '''构造函数
        
        :param rsp_queue: 对工作者请求结果的答复消息队列
        :type rsp_queue:  multiprocessing.Queue
        '''
        self._rsp_queue = rsp_queue
        self._result_dict = {}
        
    def add_result(self, result ):
        '''增加一个测试结果
        '''
        self._result_dict[id(result)] = result
        return id(result)
        
    def get_result_attr(self, objid, attrname ):
        '''获取一个测试结果的属性值
        
        :param objid: 对象ID
        :type objid: int
        :param attrname: 属性名
        :type attrname: string
        '''
        result = self._result_dict[objid]
        try:
            attr = getattr(result, attrname)
            if not isinstance(attr, types.MethodType):
                rsp = EnumProcessMsgType.Result_AttrValue, attr
            else:
                rsp = EnumProcessMsgType.Result_Func, 
            self._rsp_queue.put(rsp)
        except:
            self._rsp_queue.put((EnumProcessMsgType.Result_AttrError, 
                                 "'%s' object has no attribute '%s'" % (type(result).__name__, attrname) ))
            
    def call_result_func(self, objid, funcname, args, kwargs ):
        '''调用一个测试结果的函数
        
        :param objid: 对象ID
        :type objid: int
        :param funcname: 函数名
        :type funcname: string
        :param args: 参数
        :type args: tuple
        :param kwargs: 参数
        :type kwargs: dict
        '''
        result = self._result_dict[objid]
        try:
            rsp = EnumProcessMsgType.Result_Return, getattr(result, funcname)(*args, **kwargs)
        except:
            rsp = EnumProcessMsgType.Result_Raise, traceback.format_exc()
        self._rsp_queue.put(rsp)
            

def _log_collection_result( testreport, result_collection ):
    '''记录结果集合
    '''
    for it in result_collection:
        if isinstance(it, TestResultCollection):
            _log_collection_result(testreport, it)
        else:
            testreport.log_test_result(it.testcase, it)
                
def _run_test_thread( worker_id, ctrl_msg_queue, testcase, testreport ):
    '''执行测试用例的线程
    
    :param worker_id: 工作者ID
    :type worker_id: string
    :param ctrl_msg_queue: 控制进程的消息队列
    :type ctrl_msg_queue: multiprocessing.Queue
    :param testcase: 测试用例
    :type testcase: TestCase
    :param testreport: 测试报告
    :type testreport: ITestReport
    '''
    try:
        runnner = getattr(testcase, 'case_runner', TestCaseRunner())
        result = runnner.run(testcase, testreport.get_testresult_factory())
        if isinstance(result, TestResultCollection):
            _log_collection_result(testreport, result)
        else:
            testreport.log_test_result(result.testcase, result)
        
        ctrl_msg_queue.put((EnumProcessMsgType.Worker_Idle, worker_id, serialization.dumps(testcase), result.passed))
    except:
        ctrl_msg_queue.put((EnumProcessMsgType.Worker_Error, worker_id, traceback.format_exc()))
            
   
def _worker_process( worker_id, 
                     ctrl_msg_queue, msg_queue, rsp_queue,
                     result_factory_type, result_factory_data):
    '''执行测试的子进程过程
    
    :param worker_id: 工作者ID，全局唯一
    :type worker_id: string
    :param ctrl_msg_queue: 控制进程通信的消息队列
    :type ctrl_msg_queue: multiprocessing.Queue
    :param msg_queue: 本进程的消息队列
    :type msg_queue: multiprocessing.Queue
    :param rsp_queue: 对本进程请求结果的答复消息队列
    :type rsp_queue:  multiprocessing.Queue
    :param result_factory_type: 测试结果工厂类
    :type result_factory_type: type
    :param result_factory_data: 测试结果工厂序列化后数据
    :type result_factory_data: object
    '''
    try:
        result_factory = _EmptyClass()
        result_factory.__class__ = result_factory_type
        result_factory.loads(result_factory_data)
        result_manager = TestResultStubManager(rsp_queue)
        report = TestReportProxy(worker_id, ctrl_msg_queue, result_factory, result_manager)
        while True:
            msg = msg_queue.get()
            msg_type = msg[0]
            msg_data = msg[1:]
            
            if msg_type == EnumProcessMsgType.Worker_Quit:
                break
            
            elif msg_type == EnumProcessMsgType.Worker_RunTest:
                testcase = serialization.loads(msg_data[0])
                t = threading.Thread(target=_run_test_thread, 
                                     args=(worker_id, ctrl_msg_queue, testcase, report))
                t.daemon = True
                t.start()
                
            elif msg_type == EnumProcessMsgType.Result_GetAttr:
                objid, name = msg_data
                result_manager.get_result_attr(objid, name)
                
            elif msg_type == EnumProcessMsgType.Result_CallFunc:
                objid, func, args, kwargs = msg_data
                result_manager.call_result_func(objid, func, args, kwargs)
    except:
        ctrl_msg_queue.put((EnumProcessMsgType.Worker_Error, worker_id, traceback.format_exc()))
    
class TestWorker(object):
    '''多进程执行用例时，执行测试的子进程
    '''    
    def __init__(self, worker_id, ctrl_msg_queue, result_factory ):
        '''构造函数
        
        :param worker_id: 工作者ID，全局唯一
        :type worker_id: string
        :param ctrl_msg_queue: 控制进程的消息队列
        :type msg_queue: multiprocessing.Queue
        :param result_factory: 测试结果工厂
        :type result_factory: ITestResultFactory
        '''
        self._worker_id = worker_id
        self._result_factory = result_factory
        self._ctrl_msg_queue = ctrl_msg_queue
        self._reset()
        
    def _reset(self):
        '''重置内部状态
        '''
        self._rsp_queue = multiprocessing.Queue()
        self._msg_queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(target=_worker_process,
                                                args=(self._worker_id, 
                                                      self._ctrl_msg_queue, 
                                                      self._msg_queue,
                                                      self._rsp_queue,
                                                      type(self._result_factory),
                                                      self._result_factory.dumps()))
        self._monitor = threading.Thread(target=self._process_monitor)
        self._monitor.daemon = True
        self._testcase = None
        self._stopping = False
    
    def _process_monitor(self):
        '''监控线程
        '''
        self._process.join()
        if not self._stopping:
            self._ctrl_msg_queue.put((EnumProcessMsgType.Worker_Error, self._worker_id, 'process exit unexpectedly'))
    
    def start(self):
        '''开始执行
        '''
        self._process.start()
        self._monitor.start()
                
    def stop(self):
        '''结束执行
        '''
        self._stopping = True
        self.send_message((EnumProcessMsgType.Worker_Quit,))
        self._process.join(5)
        if self._process.is_alive():
            self._process.terminate()
    
    def restart(self):
        '''重新开始执行
        '''
        self._reset()
        self.start()
        
    def run_testcase(self, testcase ):
        '''分配一个测试用例
        
        :param testcase: 要执行的测试用例
        :type testcase: TestCase
        '''
        self.send_message((EnumProcessMsgType.Worker_RunTest, serialization.dumps(testcase)))
        self._testcase = testcase
        
    def current_testcase(self):
        '''当前正在执行的测试用例
        
        :returns: TestCase
        '''
        return self._testcase
    
    def send_message(self, msg ):
        '''发送消息到工作者
        
        :param msg: 消息
        :type msg: tuple
        '''
        self._msg_queue.put(msg)
        
    def recv_message(self, timeout=None ):
        '''接收工作者的答复消息
        '''
        if timeout is None:
            return self._rsp_queue.get()
        else:
            try:
                return self._rsp_queue.get(timeout=timeout)
            except Empty:
                raise RuntimeError("waiting response message from worker timeout")

    
class MultiProcessTestRunner(BaseTestRunner):
    '''使用多进程并发执行用例
    
    多进程并发时，有两个特殊的问题需要处理：
    
    1、测试执行工作进程需要通知TestReport测试用例的执行情况等，
    解决方案是：
    为每个工作进程提供一个TestReportProxy，TestReportProxy通过消息机制通知
    真正的TestReport
    
    2、TestReport需要访问在工作进程的TestResult对象，
    解决方案是：
    每个工作进程有一个TestResultStubManager，提供给TestReport的是一个TestResultProxy
    对象，TestResultProxy通过消息机制和TestResultStubManager通信，来获取真正的TestResult
    的信息
           
    '''
    def __init__(self, report, process_cnt=5, retries=0):
        '''构造函数
        
        :param report: 测试报告
        :type report: ITestReport
        :param process_cnt: 进程数
        :type process_cnt: int
        :param retries: 失败重跑次数上限
        :type retries: int
        '''
        self._process_cnt = int(process_cnt)
        self._retries = retries
        super(MultiProcessTestRunner,self).__init__(report)
        
    def run_all_tests(self, tests ):
        '''执行全部的测试用例
        
        :param test: 测试用例对象列表
        :type tests: list
        '''         
        if len(tests) < self._process_cnt:
            self._process_cnt = len(tests)
                         
        random.shuffle(tests)
        tests_queue = collections.deque(tests)
        tests_retry_dict = {}
        msg_queue = multiprocessing.Queue()
        workers_dict = {}
        result_factory = self.report.get_testresult_factory()
        for i in range(self._process_cnt):
            worker = TestWorker(i, msg_queue, result_factory)
            worker.start()
            worker.run_testcase(tests_queue.popleft())
            workers_dict[i] = worker
        
        idle_workers = []
        while True:
            msg = msg_queue.get()
            msg_type = msg[0]
                        
            if msg_type == EnumProcessMsgType.Report_LogTestResult:
                worker = workers_dict[msg[1]]
                testcase = serialization.loads(msg[2])
                objid, passed = msg[3], msg[4]
                self.report.log_test_result(testcase, TestResultProxy(worker, objid, passed))
            
            elif msg_type == EnumProcessMsgType.Report_LogRecord:
                self.report.log_record(msg[1], msg[2], msg[3], msg[4])
                
            elif msg_type == EnumProcessMsgType.Worker_Idle:
                worker = workers_dict[msg[1]]
                test = serialization.loads(msg[2])
                passed = msg[3]
                if not passed:
                    tests_retry_dict.setdefault(test.test_name, 0)
                    if tests_retry_dict[test.test_name] < self._retries:
                        tests_retry_dict[test.test_name] += 1
                        tests_queue.append(test)
                
                if len(tests_queue) > 0:    
                    worker.run_testcase(tests_queue.popleft())
                else:
                    idle_workers.append(worker)
                    if len(idle_workers) == len(workers_dict):
                        break
                
            elif msg_type == EnumProcessMsgType.Worker_Error:
                worker = workers_dict[msg[1]]
                err_msg = msg[2]
                self.report.error('RUNNER', 'runner process %s error occur: %s' % (msg[1], err_msg), record=dict(err_msg=err_msg))
                if worker not in idle_workers:
                    tests_queue.append(worker.current_testcase())
                    worker.restart()
                    worker.run_testcase(tests_queue.popleft())
                
        for it in workers_dict.values():
            it.stop()