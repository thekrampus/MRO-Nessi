#!/usr/bin/env python

from configobj import ConfigObj
import logging
import math
import time
import traceback
from wx.lib.pubsub import Publisher

import XPS_C8_drivers as xps
from keywords import keywords
from threadtools import run_async

cfg = ConfigObj(infile="nessisettings.ini")


def XPSErrorHandler(controller, socket, code, name):
    """
This is a general error handling function for the newport controller 
functions. First the function checks for errors in communicating with the 
controller, then it fetches the error string and displays it in a message box.  
If the error string can not be found it will print the error code for lookup 
by the user.

    Inputs: controller, socket, code, name.

    controller: [xps]   Which instance of the XPS controller to use.
    socket:     [int]   Which socket to use to communicate with the XPS 
                        controller.
    code:       [int]   The error code returned by the function that called 
                        this function.
    name:       [str]   The name of the function that called this function.
"""

    tb = traceback.format_stack()
    
    # This checks to see if the error is in communication with the controller.
    if code != -2 and code != -108:

        # Getting the error string.
        error = controller.ErrorStringGet(socket, code)
        # If the error string lookup fails, this message will display with the error code.
        if error[0] != 0:
            logging.error(name + " : ERROR "+ str(code) + '\n' + str(tb))
        # This displays the error string.
        else:
            logging.error(name + " : " + error[1] + '\n' + str(tb))
    # This code handles the case where the connection to the controller fails after initial contact.
    else:
        if code == -2:
            logging.critical(name + " : TCP timeout" + '\n' + str(tb))
        elif code == -108:
            logging.critical(name + " : The TCP/IP connection was closed by an administrator" + '\n' + str(tb))
        


def NewportWheel(controller, wheel, socket, current, position, home):
    """
A thread that initiates a move in the dewar and then monitors The Newport GPIO
for a bit flip that indicates the motor needs to be stopped.  If the motion 
fails the function will log an error in the nessi error log. If the motion 
succedes the function will log a message. The function returns the position 
of the motor upon success.

    Inputs: controller, name, socket, position, home.

    controller: [xps]   Which instance of the XPS controller to use.
    wheel:      [str]   The name of the motor that is being used.  This is for
                        config file purposes.
    socket:     [int]   Which socket to use to communicate with the XPS 
                        controller.
    current:    [int]   What position the motor is currently at.
    position:   [int]   What position the motor should move to.
    home:       [bool]  Determines whether the thread will find the home 
                        position or a different position.
"""
    # Initializing variables.
    group = cfg[wheel]["group"]
    state = 0
    speed = int(cfg[wheel]["direction"])*100
    # Different initializations depending on whether it is homing or not.
    if home == True:
        val = int(cfg[wheel]["home"]["val"])
        bit = int(cfg[wheel]["home"]["bit"])
        diff = 1
        position = 0
    else:
        val = int(cfg[wheel]["position"]["val"])
        bit = int(cfg[wheel]["position"]["bit"])
        # self.diff is how many positions away from current the target position is.
        diff = (int(cfg[wheel]["slots"]) - current + position) % int(cfg[wheel]["slots"])

    if current != position or home == True:
        # Starting motion.
        Gset = controller.GroupSpinParametersSet(socket, cfg[wheel]["group"], speed, 800)
        # Checking if the motion command was sent correctly.
        # If so then the GPIO checking begins.
        if Gset[0] != 0:
            XPSErrorHandler(controller ,socket, Gset[0], "GroupSpinParametersSet")
        else:
            # A pause to let the motor begin moving before tracking it.
            # This prevents the counter from catching the bit flip before motion begins.
            time.sleep(1)
            # This while loop runs until the motor is one position before the target.
            # It has a one second delay after catching a bit flip to allow the motor to go past the switch so it is not double counted.
            while state < diff-1:
                time.sleep(.1)
                value = controller.GPIODigitalGet(socket, "GPIO4.DI")
                #print 'loop 1', int(format(value[1], "016b")[::-1][bit])
                if value[0] != 0:
                    XPSErrorHandler(controller, socket, value[0], "GPIODigitalGet")
                elif int(format(value[1], "016b")[::-1][bit]) == val:
                    time.sleep(1)
                    state = state + 1
                else:
                    pass
            # This loop counts the switch flip with no delay so the motor can be stopped at the position.
            while state != diff:
                time.sleep(.1)
                value = controller.GPIODigitalGet(socket, "GPIO4.DI")
                #print 'loop 2:', int(format(value[1], "016b")[::-1])
                if value[0] != 0:
                    XPSErrorHandler(controller, socket, value[0], "GPIODigitalGet")
                elif  int(format(value[1], "016b")[::-1][bit]) == val:
                    stop=controller.GroupSpinModeStop(socket, cfg[wheel]["group"], 1200)
                    if stop[0] != 0:
                        XPSErrorHandler(controller, socket, stop[0], "GroupSpinModeStop")
                    elif int(format(value[1], "016b")[::-1][bit]) != val: 
                        position = -1      
                        logging.critical("motion failed, home and then reinitiate move")
                    else:
                        logging.info("motion succeded")
                        state = state + 1
                else:
                    pass
            # Stopping the motor
#            stop=controller.GroupSpinModeStop(socket, cfg[wheel]["group"], 400)
#            if stop[0] != 0:
#                XPSErrorHandler(controller, socket, stop[0], "GroupSpinModeStop")
#            # Checking to be sure the motor is in a valid position.
#            elif int(format(value[1], "016b")[::-1][bit]) != val: 
#                position = -1      
#                logging.critical("motion failed, home and then reinitiate move")
#            else:
#                logging.info("motion succeded")
             
    else:
        pass
    return position


def NewportInitialize(controller, motor, socket, home_pos):
    """
An initialization function for any motor controlled by the XPS controller.
This function returns nothing if succesful and calls XPSErrorHandler otherwise.

    Inputs: controller, motor, socket, home_position.
    
    controller: [xps]   Which instance of the XPS controller to use.
    motor:      [str]   The name of the motor that is being used.  This is for
                        config file purposes.
    socket:     [int]   Which socket to use to communicate with the XPS 
                        controller.
    home_pos:   [int]   Determines whether the thread will find the home 
                        position or a different position.
"""
    # This function kills any motors that are still active from previous motions.
    GKill = controller.GroupKill(socket, cfg[motor]["group"])   
    if GKill[0] != 0:
        XPSErrorHandler(controller, socket, GKill[0], "GroupKill")

    # This function initializes the motor so it can be moved.
    GInit = controller.GroupInitialize(socket, cfg[motor]["group"])
    if GInit[0] != 0:
        XPSErrorHandler(controller, socket, GInit[0], "GroupInitialize")

    # This function homes the motor and then moves the motor to a home position defined by the user.
    GHomeSearch = controller.GroupHomeSearchAndRelativeMove(socket, cfg[motor]["group"],[home_pos])
    if GHomeSearch[0] != 0:
        XPSErrorHandler(controller, socket, GHomeSearch[0], "GroupHomeSearchAndRelativeMove")


def NewportKmirrorMove(controller, socket, motor, jog_state, position):
    """
This function moves the k-mirror to a choosen position at 10 deg/s.

    Inputs: controller, socket, motor, jog_state, position.

    controller: [xps]   Which instance of the XPS controller to use.
    socket:     [int]   Which socket to use to communicate with the XPS 
                        controller.
    motor:      [str]   Which motor is being controlled.  This is for config 
                        file purposes.
    jog_state:  [bool]  Whether or not the motor in question is already 
                        configured for continuous rotation. 
    position:   [float] What value to move the k-mirror to.
"""
    # This checks to see if the motor is in a continuous rotation state and if it is then the function disables continuous rotation. 
    if jog_state == True:
        Gmode = controller.GroupJogModeDisable(socket, cfg[motor]["group"])
        if Gmode[0] != 0:
            XPSErrorHandler(controller, socket, Gmode[0], "GroupJogModeEnable")
    else:
        pass

    # This function sets the motion parameters to be used by the motor.
    # If the parameters are set correctly then an absolute move is made to the position of choice.
    Gset = controller.PositionerSGammaParametersSet(socket,cfg[motor]["positioner"], 10 , 200, .005, .05)
    if Gset[0] != 0:
        XPSErrorHandler(controller, socket, Gset[0], "PositionerSGammaParametersSet")
    else:
        GMove = controller.GroupMoveAbsolute(socket, cfg[motor]["group"], [float(position)])
        if GMove[0] != 0:
            XPSErrorHandler(controller, socket, GMove[0], "GroupMoveAbsolute")
        else:
            pass


def NewportKmirrorRotate(controller, socket, motor, speed):
    """
This function prepares the motor for continuous rotation if it isn"t already 
prepared and then sets a choosen velocity.

    Inputs: controller, socket, motor, jog_state, velocity.

    controller: [xps]   Which instance of the XPS controller to use.
    socket:     [int]   Which socket to use to communicate with the XPS 
                        controller.
    motor:      [str]   Which motor is being controlled.  This is for config 
                        file purposes.
    jog_state:  [bool]  Whether or not the motor in question is already 
                        configured for continuous rotation. 
    velocity:   [float] What value to set the rotational velocity to in deg/s.
"""
    # This checks if the motor is in a continuous rotation state and if not enables that state.
    Gmode = controller.GroupJogModeEnable(socket, cfg[motor]["group"])
    if Gmode[0] != 0:
        XPSErrorHandler(controller, socket, Gmode[0], "GroupJogModeEnable")
    else:
        pass
    # This sets the rotation rate for the motor. 
    # The motor will rotate until it is stopped or it hits a limit switch.
    velocity = speed*cfg[motor]["direction"]
    GJog = controller.GroupJogParametersSet(socket, cfg[motor]["group"], [velocity],[400])
    if GJog[0] != 0:
        XPSErrorHandler(controller, socket, GJog[0], "GroupJogParametersSet")

   
def NewportStatusGet(controller, socket, motor):
    """

    Inputs: controller, socket, motor.
    
    controller: [xps]   Which instance of the XPS controller to use.
    socket:     [int]   Which socket to use to communicate with the XPS
                        controller.
    motor:      [str]   Which Motor is being controlled.  This is for config
                        file purposes.
"""
    info = []
    position = controller.GroupPositionCurrentGet(socket, cfg[motor]["group"], 1)
    if position[0] != 0:
        XPSErrorHandler(controller, socket, position[0], "GroupPositionCurrentGet")
    else:
        info.append(position[1])
    profile = controller.PositionerSGammaParametersGet(socket, cfg[motor]["positioner"])
    if profile[0] != 0:
        XPSErrorHandler(controller, socket, profile[0], "PositionerSGammaParametersGet")
    else:
        for i in profile[1:]:
            info.append(i)
    return info


def NewportStop(controller, socket, motor):
    """

"""
    if motor == "kmirror":
        GStop = controller.GroupJogParametersSet(socket, cfg[motor]["group"], [0],[200])
        if GStop[0] != 0:
            XPSErrorHandler(controller, socket, GStop[0], "GroupJogParametersSet")
        else: 
            pass 
        JDisable = controller.GroupJogModeDisable(socket, cfg[motor]["group"])
        if JDisable[0] != 0:
            XPSErrorHandler(controller, socket, JDisable[0], "GroupJogModeDisable")
        else: 
            pass        
    else:
        GStop = controller.GroupSpinParametersSet(socket, cfg[motor]["group"], 0, 800)
        if GStop[0] != 0:
            XPSErrorHandler(controller, socket, GStop[0], "GroupSpinParametersSet")
        else:
            pass

@run_async
def NewportFocusLimit(controller, socket, motor):
    """

"""
    bitup = cfg[motor]["upper"]["bit"]
    bitdown = cfg[motor]["lower"]["bit"]
    valup = cfg[motor]["upper"]["val"]
    valdown = cfg[motor]["lower"]["val"]
    stop = False
    while stop == False:
        value = controller.GPIODigitalGet(socket, "GPIO4.DI")
        velocity = controller.GroupSpinCurrentGet(socket, cfg[motor]["group"])

        if value[0] != 0 or velocity[0] != 0:
            if value[0] != 0:
                stop = True
                XPSErrorHandler(controller, socket, value[0], "GPIODigitalGet")
            else:
                stop = True
                XPSErrorHandler(controller, socket, velocity[0], "GroupSpinCurrentGet")

        elif int(format(value[1], "016b")[::-1][bitup]) == valup or int(format(value[1], "016b")[::-1][bitdown]) == valdown:
            stop = True

        elif velocity[1] == 0:
            stop = True

        else:
            pass 

    GStop = controller.GroupSpinModeStop(socket, cfg[motor]["group"], 400)
    if GStop[0] != 0:
        XPSErrorHandler(controller, socket, GStop[0], "GroupSpinModeStop")
    else:
        pass
           

def NewportFocusMove(controller, socket, motor, distance, speed, direction):
    """
    Inputs: controller, socket, motor, distance, speed, direction.

    controller: [xps]   Which instance of the XPS controller to use.
    socket:     [list]  A list of two sockets to use to communicate with the 
                        XPS controller.
    motor:      [str]   Which motor is being controlled.  This is for config 
                        file purposes.
    distance:   [float] How far to move the array.
    speed:      [int]   How fast to move the array.
    direction:  [+-1]   which direction to move.
"""
    delay = speed/(distance*.576)
    velocity = speed * direction * cfg[wheel]['direction']
    NewportFocusLimit(controller, socket[0], motor)
    Gset = controller.GroupSpinParametersSet(socket[1], cfg[wheel]["group"], velocity, 600)
    if Gset[0] != 0:
        XPSErrorHandler(controller, socket[1], Gset[0], "GroupSpinParametersSet")
    else:
        pass 
    time.sleep(delay)
    GStop = controller.GroupSpinParametersSet(socket[1], cfg[motor]["group"], 0, 600)
    if GStop[0] != 0:
        Kill = controller.KillAll(socket[1])
        if Kill[0] != 0:
            XPSErrorHandler(controller, socket[1], Kill[0], "KillAll")        
        XPSErrorHandler(controller, socket[1], GStop[0], "GroupSpinModeStop")
        travel = 'ERROR'
    else:
        travel = distance
    return travel 
    

def NewportFocusHome(controller, socket, motor):
    """

"""
    bitdown = cfg[motor]["lower"]["bit"]
    valdown = cfg[motor]["lower"]["val"]
    home = True
    vel = 200*cfg[wheel]['direction']
    Gset = controller.GroupSpinParametersSet(socket, cfg[wheel]["group"], speed, 200)
        # Checking if the motion command was sent correctly.
        # If so then the GPIO checking begins.
    if Gset[0] != 0:
        XPSErrorHandler(controller ,socket, Gset[0], "GroupSpinParametersSet")
    else:
        while home == True:
            value = controller.GPIODigitalGet(socket, "GPIO4.DI")
            if int(format(value[1], "016b")[::-1][bitdown]) == valdown:
                home = False
            else:
                time.sleep(.1)
    stop = controller.GroupSpinModeStop(socket, cfg[wheel]["group"], 400)
    if stop[0] != 0:
        Kill = controller.KillAll(socket)
        if Kill[0] != 0:
            XPSErrorHandler(controller, socket, Kill[0], "KillAll")        
        XPSErrorHandler(controller, socket, stop[0], "GroupSpinModeStop")    
    else:
        pass


def NewportKmirrorTracking(parent, controller, socket, motor, t_angle):
    """
This function initiates kmirror tracking.  The tracking algorith updates the
speed of rotation based on feedback from the telescope.  If the telescope is 
not returning data then the tracking is cancelled.  tracking runs until the 
user stops it in the NESSI GUI.
    
    Inputs: parent, controller, socket, motor.
    
    parent:     [???]   The object that called the function.
    controller: [xps]   Which instance of the XPS controller to use.
    socket:     [int]   Which socket to be used to communicate with the XPS
                        controller.
    motor:      [str]   Which motor is being used.  This is for config file
                        purposes.
    t_angle:    [float] User defined angle specific to the target.

"""
    Gmode = controller.GroupJogModeEnable(socket, cfg[motor]["group"])
    if Gmode[0] != 0:
        XPSErrorHandler(controller, socket, Gmode[0], "GroupJogModeEnable")
    phi = math.radians(33.984861)
    
    while parent.trackstatus == True:
        try:
            # Getting keywords that are updated by the telescope.
            A = math.radians(keywords['TELAZ'])
            H = math.radians(keywords['TELALT'])
            PA = float(keywords['PA'])
        except TypeError:
            parent.trackstatus = False
            time.sleep(1)
        else:
            vel = ((-.262)*(.5)*3600*math.pi*math.cos(phi)*math.cos(A))/(math.cos(H)*180)
            delta = vel - parent.vel
            parent.vel = parent.vel + delta
            velocity = parent.vel*cfg[motor]["direction"]
            GJog = controller.GroupJogParametersSet(socket, cfg[motor]["group"], [velocity],[400])
            if GJog[0] != 0:
                XPSErrorHandler(controller, socket, GJog[0], "GroupJogParametersSet")
            time.sleep(1)
        

# Test code to be removed later
if __name__ == "__main__":

    x=xps.XPS()
    open_sockets=[]
    used_sockets=[]

    for i in range(int(cfg["general"]["sockets"])):
        open_sockets.append(x.TCP_ConnectToServer("192.168.0.254",5001,1))
    
    for i in range(int(cfg["general"]["sockets"])):
        if open_sockets[i] == -1:
            print "Error, Sockets not opened."
    NewportInitialize(x, "mask", open_sockets[0], 0)
    pos = NewportWheelThread(x, "mask", open_sockets[0], 1, 4, True)
    pos = NewportWheelThread(x, "mask", open_sockets[0], pos, 1, False)

    