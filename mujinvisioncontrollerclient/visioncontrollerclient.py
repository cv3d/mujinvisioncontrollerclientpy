# -*- coding: utf-8 -*-
# Copyright (C) 2012-2017 MUJIN Inc
# Mujin vision controller client for bin picking task

# system imports
import zmq
import json

# mujin imports
from mujincontrollerclient import zmqclient
from . import VisionControllerClientError

# logging
from logging import getLogger
log = getLogger(__name__)

"""
vmState (dict): Parameters needed for some visionmanager commands
    mujinControllerIp (str): controller client ip
    mujinControllerPort (int): controller client port
    mujinControllerUsernamePass (str): controller client "{0}:{1}".format(username, password)

    binpickingTaskZmqPort (str):
    binpickingTaskHeartbeatPort (int):
    binpickingTaskHeartbeatTimeout (double): in seconds
    binpickingTaskScenePk (str):
    defaultTaskParameters (str): Params vision manager has to send to every request it makes to the mujin controller
    slaverequestid (str):
    controllertimeout (double): Controller command timeout in seconds (Default: 10s)
    tasktype (str): Controller client tasktype

    streamerIp (str):
    streamerPort (int):
    imagesubscriberconfig (str): JSON string
    containerParameters (dict):

    targetname (str):
    targeturi (str):
    targetupdatename (str): Name of the detected target which will be returned from detector.
                            If not set, then the value from initialization will be used
    detectorconfigname (str): name of detector config
    targetdetectionarchiveurl (str): full url to download the target archive containing detector conf and templates

    locale (str): (Default: en_US)

    visionmanagerconfig (str): JSON string
    sensormapping(dict): cameraname(str) -> cameraid(str)
"""

class VisionControllerClient(object):
    """mujin vision controller client for bin picking task
    """

    _isok = False  # False indicates that the client is about to be destroyed
    _ctx = None  # zeromq context to use
    _ctxown = None  # if owning the zeromq context, need to destroy it once done, so this value is set
    hostname = None  # hostname of vision controller
    commandport = None  # command port of vision controller
    configurationport = None  # configuration port of vision controller, usually command port + 2

    def __init__(self, hostname, commandport, ctx=None):
        """connects to vision server, initializes vision server, and sets up parameters
        :param hostname: e.g. visioncontroller1
        :param commandport: e.g. 7004
        :param ctx: zmq context
        """
        self.hostname = hostname
        self.commandport = commandport
        self.configurationport = commandport + 2

        if ctx is None:
            assert(self._ctxown is None)
            self._ctxown = zmq.Context()
            self._ctxown.linger = 100
            self._ctx = self._ctxown
        else:
            self._ctx = ctx

        self._commandsocket = zmqclient.ZmqClient(self.hostname, commandport, self._ctx)
        self._configurationsocket = zmqclient.ZmqClient(self.hostname, self.configurationport, self._ctx)
        self._isok = True
    
    def __del__(self):
        self.Destroy()
    
    def Destroy(self):
        self.SetDestroy()

        if self._commandsocket is not None:
            try:
                self._commandsocket.Destroy()
                self._commandsocket = None
            except:
                log.exception()

        if self._configurationsocket is not None:
            try:
                self._configurationsocket.Destroy()
                self._configurationsocket = None
            except:
                log.exception()

        if self._ctxown is not None:
            try:
                self._ctxown.destroy()
                self._ctxown = None
            except:
                log.exception()

        self._ctx = None

    def SetDestroy(self):
        self._isok = False
        if self._commandsocket is not None:
            self._commandsocket.SetDestroy()
        if self._configurationsocket is not None:
            self._configurationsocket.SetDestroy()
    
    def _ExecuteCommand(self, command, fireandforget=False, timeout=2.0):
        response = self._commandsocket.SendCommand(command, fireandforget=fireandforget, timeout=timeout)
        if fireandforget:
            return None
        if 'error' in response:
            if isinstance(response['error'], dict):  # until vision manager error handling is resolved
                raise VisionControllerClientError(response['error'].get('type', ''), response['error'].get('desc', ''))

            else:
                raise VisionControllerClientError('unknownerror', u'Got unknown formatted error %r' % response['error'])
        if 'computationtime' in response:
            log.verbose('%s took %f seconds' % (command['command'], response['computationtime'] / 1000.0))
        else:
            log.verbose('%s executed successfully' % (command['command']))
        return response

    def GatherVisionManagerCommandState(self, vmState, controllerclient):
        """
        :param vmState (dict): kv pairs created from controlelrclient will be added to this dict
        :param controllerclient: pointer to the BinpickingControllerClient that connects to the mujin controller we want the vision server to talk to
        """
        if 'mujinControllerIp' not in vmState:
            vmState['mujinControllerIp'] = controllerclient.controllerIp
        vmState.update({
            # controllerClientInfo            
            'mujinControllerPort': controllerclient.controllerPort,
            'mujinControllerUsernamePass': '%s:%s' % (controllerclient.controllerusername, controllerclient.controllerpassword),
            # binpickingTask
            'binpickingTaskZmqPort': controllerclient.taskzmqport,
            'binpickingTaskHeartbeatPort': controllerclient.taskheartbeatport,
            'binpickingTaskHeartbeatTimeout': controllerclient.taskheartbeattimeout,
            'binpickingTaskScenePk': controllerclient.scenepk,
            'tasktype': controllerclient.tasktype,
            'slaverequestid': controllerclient.GetSlaveRequestId()
        })

    def IsDetectionRunning(self, timeout=10.0):
        log.verbose('checking detection status...')
        command = {'command': 'IsDetectionRunning'}
        return self._ExecuteCommand(command, timeout=timeout)['isdetectionrunning']
    
    def DetectObjects(self, vmState, regionname=None, cameranames=None, ignoreocclusion=None, newerthantimestamp=None, fastdetection=None, bindetection=None, request=False, timeout=10.0):
        """detects objects
        :param vmState (dict): See documentation at the top of the file
        :param regionname: name of the bin
        :param cameranames: a list of names of cameras to use for detection, if None, then use all cameras available
        :param ignoreocclusion: whether to skip occlusion check
        :param newerthantimestamp: if specified, starttimestamp of the image must be newer than this value in milliseconds
        :param fastdetection: whether to prioritize speed
        :param bindetection: whether to detect bin
        :param request: whether to request new images instead of getting images off the buffer
        :param timeout in seconds
        :return: detected objects in world frame in a json dictionary, the translation info is in millimeter, e.g. {'objects': [{'name': 'target_0', 'translation_': [1,2,3], 'quat_': [1,0,0,0], 'confidence': 0.8}]}
        """
        log.verbose('Detecting objects...')
        command = {"command": "DetectObjects",
                   }
        command.update(vmState)
        if regionname is not None:
            command['regionname'] = regionname
        if cameranames is not None:
            command['cameranames'] = list(cameranames)
        if ignoreocclusion is not None:
            command['ignoreocclusion'] = int(ignoreocclusion)
        if newerthantimestamp is not None:
            command['newerthantimestamp'] = newerthantimestamp
        if fastdetection is not None:
            command['fastdetection'] = int(fastdetection)
        if bindetection is not None:
            command['bindetection'] = int(bindetection)
        if request is not None:
            command['request'] = 1 if request is True else 0
        return self._ExecuteCommand(command, timeout=timeout)

    def StartDetectionThread(self, vmState, regionname=None, cameranames=None, executionverificationcameranames=None, worldResultOffsetTransform=None, ignoreocclusion=None, obstaclename=None, detectionstarttimestamp=None, locale=None, maxnumfastdetection=1, maxnumdetection=0, sendVerificationPointCloud=None, stopOnLeftInOrder=None, timeout=2.0, targetupdatename="", numthreads=None, cycleindex=None, destregionname=None):
        """starts detection thread to continuously detect objects. the vision server will send detection results directly to mujin controller.
        :param vmState (dict): See documentation at the top of the file
        :param targetname: name of the target
        :param regionname: name of the bin
        :param cameranames: a list of names of cameras to use for detection, if None, then use all cameras available
        :param cameranames: a list of names of cameras to use for execution verification, if None, then use all cameras available
        :param worldResultOffsetTransform: the offset to be applied to detection result, in the format of {'translation_': [1,2,3], 'quat_': [1,0,0,0]}, unit is millimeter
        :param ignoreocclusion: whether to skip occlusion check
        :param obstaclename: name of the collision obstacle
        :param detectionstarttimestamp: min image time allowed to be used for detection, if not specified, only images taken after this call will be used
        :param sendVerificationPointCloud: if True, then send the verification point cloud via AddPointCloudObstacle
        :param timeout in seconds
        :param targetupdatename name of the detected target which will be returned from detector. If not set, then the value from initialization will be used
        :param numthreads Number of threads used by different libraries that are used by the detector (ex. OpenCV, BLAS). If 0 or None, defaults to the max possible num of threads
        :param cycleindex: cycle index
        :param destregionname: name of the destination region
        :return: returns immediately once the call completes
        """
        log.verbose('Starting detection thread...')
        command = {'command': 'StartDetectionLoop',
                   'maxnumfastdetection': maxnumfastdetection,
                   'maxnumdetection': maxnumdetection,
                   'targetupdatename': targetupdatename
                   }
        command.update(vmState)
        if regionname is not None:
            command['regionname'] = regionname
        if cameranames is not None:
            command['cameranames'] = list(cameranames)
        if executionverificationcameranames is not None:
            command['executionverificationcameranames'] = list(executionverificationcameranames)
        if ignoreocclusion is not None:
            command['ignoreocclusion'] = 1 if ignoreocclusion is True else 0
        if obstaclename is not None:
            command['obstaclename'] = obstaclename
        if detectionstarttimestamp is not None:
            command['detectionstarttimestamp'] = detectionstarttimestamp
        if locale is not None:
            command['locale'] = locale
        if sendVerificationPointCloud is not None:
            command['sendVerificationPointCloud'] = sendVerificationPointCloud
        if stopOnLeftInOrder is not None:
            command['stoponleftinorder'] = stopOnLeftInOrder
        if worldResultOffsetTransform is not None:
            assert(len(worldResultOffsetTransform.get('translation_', [])) == 3)
            assert(len(worldResultOffsetTransform.get('quat_', [])) == 4)
            command['worldresultoffsettransform'] = worldResultOffsetTransform
        if numthreads is not None:
            command['numthreads'] = numthreads
        if cycleindex is not None:
            command['cycleindex'] = cycleindex
        if destregionname is not None:
            command['destregionname'] = destregionname
        return self._ExecuteCommand(command, timeout=timeout)
    
    def StopDetectionThread(self, fireandforget=False, timeout=2.0):
        """stops detection thread
        :param timeout in seconds
        """
        log.verbose('Stopping detection thread...')
        command = {"command": "StopDetectionLoop"}
        return self._ExecuteCommand(command, fireandforget=fireandforget, timeout=timeout)

    def SendPointCloudObstacleToController(self, vmState, regionname=None, cameranames=None, detectedobjects=None, obstaclename=None, newerthantimestamp=None, request=True, async=False, timeout=2.0):
        """Updates the point cloud obstacle with detected objects removed and sends it to mujin controller
        :param vmState (dict): See documentation at the top of the file
        :param regionname: name of the region
        :param cameranames: a list of camera names to use for visualization, if None, then use all cameras available
        :param detectedobjects: a list of detected objects in world frame, the translation info is in meter, e.g. [{'name': 'target_0', 'translation_': [1,2,3], 'quat_': [1,0,0,0], 'confidence': 0.8}]
        :param obstaclename: name of the obstacle
        :param newerthantimestamp: if specified, starttimestamp of the image must be newer than this value in milliseconds
        :param request: whether to take new images instead of getting off buffer
        :param async: whether the call is async
        :param timeout in seconds
        """
        log.verbose('Sending point cloud obstacle to mujin controller...')
        command = {'command': 'SendPointCloudObstacleToController'}
        command.update(vmState)
        if regionname is not None:
            command['regionname'] = regionname
        if cameranames is not None:
            command['cameranames'] = list(cameranames)
        if detectedobjects is not None:
            command['detectedobjects'] = list(detectedobjects)
        if newerthantimestamp is not None:
            command['newerthantimestamp'] = newerthantimestamp
        if obstaclename is not None:
            command['obstaclename'] = obstaclename
        if request is not None:
            command['request'] = 1 if request is True else 0
        if async is not None:
            command['async'] = 1 if async is True else 0
        return self._ExecuteCommand(command, timeout=timeout)

    def VisualizePointCloudOnController(self, vmState, regionname=None, cameranames=None, pointsize=None, ignoreocclusion=None, newerthantimestamp=None, request=True, timeout=2.0, filteringsubsample=None, filteringvoxelsize=None, filteringstddev=None, filteringnumnn=None):
        """Visualizes the raw camera point clouds on mujin controller
        :param vmState (dict): See documentation at the top of the file
        :param regionname: name of the region
        :param cameranames: a list of camera names to use for visualization, if None, then use all cameras available
        :param pointsize: in meter
        :param ignoreocclusion: whether to skip occlusion check
        :param newerthantimestamp: if specified, starttimestamp of the image must be newer than this value in milliseconds
        :param request: whether to take new images instead of getting off buffer
        :param timeout in seconds
        :param filteringvoxelsize in millimeter
        """
        log.verbose('sending camera point cloud to mujin controller...')
        command = {'command': 'VisualizePointCloudOnController'}
        command.update(vmState)
        if regionname is not None:
            command['regionname'] = regionname
        if cameranames is not None:
            command['cameranames'] = list(cameranames)
        if pointsize is not None:
            command['pointsize'] = pointsize
        if ignoreocclusion is not None:
            command['ignoreocclusion'] = 1 if ignoreocclusion is True else 0
        if newerthantimestamp is not None:
            command['newerthantimestamp'] = newerthantimestamp
        if request is not None:
            command['request'] = 1 if request is True else 0
        if filteringsubsample is not None:
            command['filteringsubsample'] = filteringsubsample
        if filteringvoxelsize is not None:
            command['filteringvoxelsize'] = filteringvoxelsize
        if filteringstddev is not None:
            command['filteringstddev'] = filteringstddev
        if filteringnumnn is not None:
            command['filteringnumnn'] = filteringnumnn
        return self._ExecuteCommand(command, timeout=timeout)

    def ClearVisualizationOnController(self, fireandforget=False, timeout=2.0):
        """Clears visualization made by VisualizePointCloudOnController
        :param timeout in seconds
        """
        log.verbose("clearing visualization on mujin controller...")
        command = {'command': 'ClearVisualizationOnController'}
        return self._ExecuteCommand(command, fireandforget=fireandforget, timeout=timeout)
    
    def StartVisualizePointCloudThread(self, vmState, regionname=None, cameranames=None, pointsize=None, ignoreocclusion=None, newerthantimestamp=None, request=True, timeout=2.0, filteringsubsample=None, filteringvoxelsize=None, filteringstddev=None, filteringnumnn=None):
        """Start point cloud visualization thread to sync camera info from the mujin controller and send the raw camera point clouds to mujin controller
        :param vmState (dict): See documentation at the top of the file
        :param regionname: name of the region
        :param cameranames: a list of camera names to use for visualization, if None, then use all cameras available
        :param pointsize: in meter
        :param ignoreocclusion: whether to skip occlusion check
        :param newerthantimestamp: if specified, starttimestamp of the image must be newer than this value in milliseconds
        :param request: whether to take new images instead of getting off buffer
        :param timeout in seconds
        :param filteringvoxelsize in millimeter
        """
        log.verbose('Starting visualize pointcloud thread...')
        command = {'command': 'StartVisualizePointCloudThread',
                   }
        command.update(vmState)
        if regionname is not None:
            command['regionname'] = regionname
        if cameranames is not None:
            command['cameranames'] = list(cameranames)
        if pointsize is not None:
            command['pointsize'] = pointsize
        if ignoreocclusion is not None:
            command['ignoreocclusion'] = 1 if ignoreocclusion is True else 0
        if newerthantimestamp is not None:
            command['newerthantimestamp'] = newerthantimestamp
        if request is not None:
            command['request'] = 1 if request is True else 0
        if filteringsubsample is not None:
            command['filteringsubsample'] = filteringsubsample
        if filteringvoxelsize is not None:
            command['filteringvoxelsize'] = filteringvoxelsize
        if filteringstddev is not None:
            command['filteringstddev'] = filteringstddev
        if filteringnumnn is not None:
            command['filteringnumnn'] = filteringnumnn
        return self._ExecuteCommand(command, timeout=timeout)
    
    def StopVisualizePointCloudThread(self, fireandforget=False, timeout=2.0, clearPointCloud=False):
        """Stops visualize point cloud thread
        :param timeout in seconds
        :param clearPointCloud: whether to also clear pointcloud on controller
        """
        log.verbose("Stopping visualzie pointcloud thread...")
        command = {'command': 'StopVisualizePointCloudThread', 'clearPointCloud': clearPointCloud}
        return self._ExecuteCommand(command, fireandforget=fireandforget, timeout=timeout)
    
    def GetVisionmanagerConfig(self, timeout=2.0):
        """Gets the current visionmanager config json string
        """
        log.verbose('getting current visionmanager config...')
        command = {'command': 'GetVisionmanagerConfig'}
        return self._ExecuteCommand(command, timeout=timeout)

    def GetDetectorConfig(self, timeout=2.0):
        """Gets the current detector config json string
        """
        log.verbose('getting current detector config...')
        command = {'command': 'GetDetectorConfig'}
        return self._ExecuteCommand(command, timeout=timeout)

    def GetImagesubscriberConfig(self, timeout=2.0):
        """Gets the current imagesubscriber config json string
        """
        log.verbose('getting current imagesubscriber config...')
        command = {'command': 'GetImagesubscriberConfig'}
        return self._ExecuteCommand(command, timeout=timeout)

    def SaveVisionmanagerConfig(self, visionmanagerconfigname, config="", timeout=2.0):
        """Saves the visionmanager config to disk
        :param visionmanagerconfigname name of the visionmanager config
        :param config if not specified, then saves the current config
        """
        log.verbose('saving visionmanager config to disk...')
        command = {'command': 'SaveVisionmanagerConfig'}
        if config != '':
            command['config'] = config
        return self._ExecuteCommand(command, timeout=timeout)

    def SaveDetectorConfig(self, detectorconfigname, config="", timeout=2.0):
        """Saves the detector config to disk
        :param detectorconfigname name of the detector config
        :param config if not specified, then saves the current config
        """
        log.verbose('saving detector config to disk...')
        command = {'command': 'SaveDetectorConfig'}
        if config != '':
            command['config'] = config
        return self._ExecuteCommand(command, timeout=timeout)

    def SaveImagesubscriberConfig(self, imagesubscriberconfigname, config="", timeout=2.0):
        """Saves the imagesubscriber config to disk
        :param imagesubscriberconfigname name of the imagesubscriber config
        :param config if not specified, then saves the current config
        """
        log.verbose('saving imagesubscriber config to disk...')
        command = {'command': 'SaveImagesubscriberConfig'}
        if config != '':
            command['config'] = config
        return self._ExecuteCommand(command, timeout=timeout)

    def BackupVisionLog(self, cycleIndex):
        command = {'command': 'BackupDetectionLogs', 'cycleIndex': cycleIndex}
        return self._ExecuteCommand(command, timeout=timeout)

    ############################
    # internal methods
    ############################

    def UpdateDetectedObjects(self, vmState, regionname, objects, state=None, sendtocontroller=False, timeout=2.0):
        """updates the list of objects the vision server maintains
        usage: user may want to process the object location locally and then update the list on the vision server to improve detection
        :param vmState (dict): See documentation at the top of the file
        :param regionname: regionname
        :param objects: list of dictionaries of object info
        :param state: dict of additional object info
        :param sendtocontroller: whether to send the list to mujin controller
        :param timeout in seconds
        """
        log.verbose('Updating objects...')
        command = {"command": "UpdateDetectedObjects",
                   "regionname": regionname,
                   "detectedobjects": objects,
                   "sendtocontroller": sendtocontroller}
        command.update(vmState)
        if state is not None:
            state = json.dumps(state)
            command['state'] = state
        return self._ExecuteCommand(command, timeout=timeout)

    def SyncRegion(self, vmState, regionname=None, timeout=2.0):
        """updates vision server with the lastest container info on mujin controller
        usage: user may want to update the region's transform on the vision server after it gets updated on the mujin controller
        :param vmState (dict): See documentation at the top of the file
        :param regionname: name of the bin
        :param timeout in seconds
        """
        log.verbose('Updating region...')
        command = {'command': 'SyncRegion'}
        command.update(vmState)
        if regionname is not None:
            command['regionname'] = regionname
        return self._ExecuteCommand(command, timeout=timeout)

    def SyncCameras(self, vmState, regionname=None, cameranames=None, timeout=2.0):
        """updates vision server with the lastest camera info on mujin controller
        usage: user may want to update a camera's transform on the vision server after it gets updated on the mujin controller
        :param vmState (dict): See documentation at the top of the file
        :param regionname: name of the bin, of which the relevant camera info gets updated
        :param cameranames: a list of names of cameras, if None, then use all cameras available
        :param timeout in seconds
        """
        log.verbose('Updating cameras...')
        command = {'command': 'SyncCameras',
                   }
        command.update(vmState)
        if regionname is not None:
            command['regionname'] = regionname
        if cameranames is not None:
            command['cameranames'] = list(cameranames)
        return self._ExecuteCommand(command, timeout=timeout)

    def GetCameraId(self, cameraname, timeout=2.0):
        """gets the id of the camera
        :param cameraname: name of the camera
        :param timeout in seconds
        """
        log.verbose("Getting camera id...")
        command = {'command': 'GetCameraId',
                   'cameraname': cameraname}
        return self._ExecuteCommand(command, timeout=timeout)

    def GetStatusPort(self, timeout=2.0):
        """gets the status port of visionmanager
        """
        log.verbose("Getting status port...")
        command = {'command': 'GetStatusPort'}
        return self._ExecuteCommand(command, timeout=timeout)

    def GetConfigPort(self, timeout=2.0):
        """gets the config port of visionmanager
        """
        log.verbose("Getting config port...")
        command = {'command': 'GetConfigPort'}
        return self._ExecuteCommand(command, timeout=timeout)

    def GetLatestDetectedObjects(self, returnpoints=False, timeout=2.0):
        """gets the latest detected objects
        """
        log.verbose("Getting latest detected objects...")
        command = {'command': 'GetLatestDetectedObjects', 'returnpoints': returnpoints}
        return self._ExecuteCommand(command, timeout=timeout)

    def GetStatistics(self, timeout=2.0):
        """gets the latest vision stats
        """
        log.verbose("Getting latest vision stats...")
        command = {'command': 'GetStatistics'}
        return self._ExecuteCommand(command, timeout=timeout)

    def _SendConfiguration(self, configuration, fireandforget=False, timeout=2.0):
        try:
            return self._configurationsocket.SendCommand(configuration, fireandforget=fireandforget, timeout=timeout)
        except:
            log.exception('occured while sending configuration %r', configuration)
            raise

    def Ping(self, timeout=2.0):
        return self._SendConfiguration({"command": "Ping"}, timeout=timeout)

    def Cancel(self, timeout=2.0):
        log.info('canceling command...')
        response = self._SendConfiguration({"command": "Cancel"}, timeout=timeout)
        log.info('command is stopped')
        return response

    def Quit(self, timeout=2.0):
        log.info('stopping visionserver...')
        response = self._SendConfiguration({"command": "Quit"}, timeout=timeout)
        log.info('visionserver is stopped')
        return response
