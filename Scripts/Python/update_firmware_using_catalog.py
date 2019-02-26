"""
SYNOPSIS
---------------------------------------------------------------------
 Script to update firmware using catalog

DESCRIPTION
---------------------------------------------------------------------
 This script exercises the OME REST API to allow updating a firmware using catalog.

 Note that the credentials entered are not stored to disk.

EXAMPLE
---------------------------------------------------------------------
python update_firmware_using_catalog_3.0.py --ip <ip addr> --user admin
    --password <passwd> --groupid 25315
"""
import json
import sys
import time
import argparse
from argparse import RawTextHelpFormatter
import requests
import urllib3
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

CATALOGDETAILS = []
CATALOG_INFO = {}
BASELINE_INFO = {}


def authenticate_with_ome(ip_address, user_name, password):
    """ X-auth session creation """
    auth_success = False
    session_url = "https://%s/api/SessionService/Sessions" % ip_address
    user_details = {'UserName': user_name,
                    'Password': password,
                    'SessionType': 'API'}
    headers = {'content-type': 'application/json'}
    session_info = requests.post(session_url, verify=False,
                                 data=json.dumps(user_details),
                                 headers=headers)
    if session_info.status_code == 201:
        headers['X-Auth-Token'] = session_info.headers['X-Auth-Token']
        auth_success = True
    else:
        error_msg = "Failed create of session with {0} - Status code = {1}"
        print(error_msg.format(ip_address, session_info.status_code))
    return auth_success, headers


def check_for_existing_catalog(ip_address, headers):
    """ Check if existing catalog exists """
    url = 'https://%s/api/UpdateService/Catalogs' % ip_address
    response = requests.get(url, headers=headers, verify=False)
    if response.status_code == 200:
        dev_response = response.json()
        if dev_response['@odata.count'] > 0:
            process_value_node(dev_response)
        return CATALOGDETAILS
    raise Exception("Unable to retrieve catalog information")

def process_value_node(dev_response):
    """ Processing each value to extract catalog id, baseline id
    and repository id.
    """
    associated_baseline_list = []
    i = 0
    while i < len(dev_response["value"]):
        if dev_response["value"][i].get("Repository")["Source"] == "downloads.dell.com":
            if dev_response["value"][i].get("AssociatedBaselines"):
            #len(dev_response["value"][i].get("AssociatedBaselines")) > 0:
                j = 0
                while j < len(dev_response["value"][i].get("AssociatedBaselines")):
                    associated_baseline_list.append(
                        dev_response["value"][i].get(
                            "AssociatedBaselines")[j]["BaselineId"])
                    j += 1
                CATALOGDETAILS.append(
                    {'REPO_ID': dev_response["value"][i].get("Repository")["Id"],
                     'CATALOG_ID': dev_response["value"][i]["Id"],
                     'associated_baseline_id': associated_baseline_list})
            else:
                CATALOGDETAILS.append(
                    {'REPO_ID': dev_response["value"][i].get("Repository")["Id"],
                     'CATALOG_ID': dev_response["value"][i]["Id"],
                     'associated_baseline_id': []})
        i += 1
    return CATALOGDETAILS

def delete_catalog(ip_address, headers):
    """ Delete existing catalog from dell repo """
    url = 'https://%s/api/UpdateService/Actions/UpdateService.RemoveCatalogs' % ip_address
    catalog_list = [d['CATALOG_ID'] for d in CATALOGDETAILS]
    payload = catalog_deletion_payload(catalog_list)
    status, data = request(ip_address=ip_address, url=url,
                           header=headers, payload=payload, method='POST')
    return status, data


def delete_baseline(ip_address, headers, baseline_list):
    """ Delete existing baseline from dell repo """
    url = 'https://%s/api/UpdateService/Actions/UpdateService.RemoveBaselines' % ip_address
    payload = baseline_deletion_payload(baseline_list)
    status, data = request(ip_address=ip_address, url=url,
                           header=headers, payload=payload, method='POST')
    return status, data


def catalog_creation(ip_address, headers):
    """ Create new catalog """
    url = 'https://%s/api/UpdateService/Catalogs' % ip_address
    print("Creating new catalog.!")
    payload = catalog_creation_payload()
    status, data = request(ip_address=ip_address, url=url,
                           header=headers, payload=payload, method='POST')
    if status != 201:
        raise Exception("unable to create Catalog", data)
    time.sleep(60)
    get_catalog_status, get_catalog_data = request(ip_address=ip_address, url=url, header=headers)
    if get_catalog_status == 200 and get_catalog_data["@odata.count"] != 0:
        if get_catalog_data["value"][0].get("Repository")["Source"] == "downloads.dell.com":
            return get_catalog_data["value"][0]["Id"]
        raise Exception("Exiting the code, Unable to create catalog")
    else:
        raise Exception("Exiting the code, Unable to create catalog : System Info ", sys.exc_info())


def baseline_creation(ip_address, headers, param_map):
    """ Create new baseline """
    global CATALOG_INFO
    url = 'https://%s/api/UpdateService/Baselines' % ip_address
    print("Creating new Baseline.!")
    CATALOG_INFO = get_catalog_details(ip_address, headers)
    if param_map['group_id']:
        group_type, group_name = get_group_details(ip_address, headers, param_map['group_id'])
        payload = baseline_creation_payload(CATALOG_INFO["CATALOG_ID"],
                                            CATALOG_INFO["REPO_ID"], param_map['group_id'],
                                            group_type, "GROUP")
    else:
        device_type, device_name = get_device_details(ip_address, headers, param_map['device_id'])
        payload = baseline_creation_payload(CATALOG_INFO["CATALOG_ID"],
                                            CATALOG_INFO["REPO_ID"], param_map['device_id'],
                                            device_type, device_name)
    baseline_status, baseline_data = request(ip_address=ip_address, url=url,
                                             header=headers, payload=payload, method='POST')
    if baseline_status == 201:
        time.sleep(90)
        id_repo = CATALOG_INFO.get("REPO_ID")
        id_cat = CATALOG_INFO.get("CATALOG_ID")
        return get_baseline_id(ip_address, headers, id_repo, id_cat)
    raise Exception("Unable to create baseline, Job status : ", baseline_status)


def check_device_compliance_report(ip_address, headers, id_baseline):
	compliance_report_list = []
	device_compliance_report_hash = {}
	source_names = None
	compl_url = "https://%s/api/UpdateService/Baselines(%s)/DeviceComplianceReports"%(ip_address,id_baseline)
	component_status, component_data = request(ip_address=ip_address, url=compl_url, header=headers)
	if (component_status == 200 and len(component_data["value"]) > 0):
		comp_val_list = component_data["value"]
		response_flag = check_response_type(comp_val_list)
		if response_flag:
			for compliance_dict in comp_val_list:
				compliance_list = compliance_dict.get('ComponentComplianceReports')
				if (len(compliance_list)):
					for component in compliance_list:
						if component["Version"] > component["CurrentVersion"]:
							if source_names:
								source_names = source_names + ';' + component["SourceName"]
							else:
								source_names = component["SourceName"]
						if (source_names):
							device_compliance_report_hash["Id"] = compliance_dict.get("DeviceId")
							device_compliance_report_hash["Data"] = source_names
							compliance_report_list.append(device_compliance_report_hash)
		else:
			for compliance_dict in comp_val_list:
				compliance_report_list.append({"DeviceId": compliance_dict.get("DeviceId")})
				navigation_url_link = compliance_dict.get('ComponentComplianceReports@odata.navigationLink')
				navigation_url = "https://(%s)(%s)"%(ip_address,navigation_url_link)
				print "navigation_url = %s"%navigation_url
				component_status,component_data = request(ip_address=ip_address, url=navigation_url, header=headers)
				if (component_status == 200 and (len(component_data["value"]))):
					comp_val_list = component_data["value"]
					for compliance_dict in comp_val_list:
						if (compliance_dict):
							for component in compliance_dict:
								if component["Version"] > component["CurrentVersion"]:
									if source_names:
										source_names = source_names + ';' + component["SourceName"]
									else:
										source_names = component["SourceName"]
						if (source_names):
							device_compliance_report_hash["Id"] = compliance_dict.get("DeviceId")
							device_compliance_report_hash["Data"] = source_names
							compliance_report_list.append(device_compliance_report_hash)
				else:
					sys.exit("component data is empty")
	else:	
		raise Exception("Unable to get compliance data")
	return compliance_report_list

def create_target_payload(compliance_data_list):
    my_dist = {}
    target_list = []
    for data in compliance_data_list:
        for key, value in data.items():
            if key == "Id":
                my_dist["Id"] = value
                my_dist["TargetType"] = {
                    "Id": 1000,
                    "Name": "DEVICE"
                }
            if key == "Data":
                my_dist["Data"] = value

        if my_dist["Data"] != "":
            target_list.append(my_dist.copy())
    if len(target_list) > 0:
        return target_list
    else:
        return 0
	
def check_response_type(comp_val_list):
	flag = False
	for val in comp_val_list:
		if 'ComponentComplianceReports' in val:
			flag = True
	return flag


def firmware_update(ip_address, headers, repository_id, id_cat, id_baseline, target_data):
    """ Updates Firmware """
    job_type_id = 0
    status, job_type_response_data = get_job_types(ip_address, headers)
    if status == 200:
        values = len(job_type_response_data["value"])
        job_type_id = get_job_type_id(values, job_type_response_data)
        payload = create_payload_for_firmware_update(job_type_id, str(id_baseline),
                                                     str(id_cat), str(repository_id), target_data)
        url = 'https://{0}/api/JobService/Jobs'.format(ip_address)
        update_status, update_data = request(ip_address=ip_address, url=url,
                                             header=headers, payload=payload, method='POST')
        if update_status == 201 and  update_data != 0:
            job_id = update_data["Id"]
            if job_id != -1 or job_id != 0 or job_id is not None:
                track_job_to_completion(ip_address, headers, job_id)
        else:
            print("unsuccessful or Unable to get job id")
    else:
        print("unable to get job types")


def get_job_type_id(values, job_type_response_data):
    """ Return the id of Job Type which has name Update Task """
    i = 0
    while i < values:
        if job_type_response_data["value"][i]["Name"] == "Update_Task":
            job_type_id = job_type_response_data["value"][i]["Id"]
            return job_type_id
        i += 1
    return 0
def track_job_to_completion(ip_address, headers, job_id):
    """ Tracks the update job to completion / error """
    job_status_map = {
        "2020": "Scheduled",
        "2030": "Queued",
        "2040": "Starting",
        "2050": "Running",
        "2060": "Completed",
        "2070": "Failed",
        "2090": "Warning",
        "2080": "New",
        "2100": "Aborted",
        "2101": "Paused",
        "2102": "Stopped",
        "2103": "Canceled"
    }
    max_retries = 20
    sleep_interval = 60
    failed_job_status = [2070, 2090, 2100, 2101, 2102, 2103]
    job_url = 'https://%s/api/JobService/Jobs(%s)' % (ip_address, job_id)
    loop_ctr = 0
    job_incomplete = True
    print("Polling %s to completion ..." % job_id)
    while loop_ctr < max_retries:
        loop_ctr += 1
        time.sleep(sleep_interval)
        job_resp = requests.get(job_url, headers=headers, verify=False)
        if job_resp.status_code == 200:
            job_status = str((job_resp.json())['LastRunStatus']['Id'])
            print("Iteration %s: Status of %s is %s" % (loop_ctr, job_id,
                                                        job_status_map[job_status]))
            if int(job_status) == 2060:
                job_incomplete = False
                print("Completed updating firmware successfully ... Exiting")
                break
            elif int(job_status) in failed_job_status:
                job_incomplete = False
                print("Update job failed ... ")
                job_hist_url = str(job_url) + "/ExecutionHistories"
                job_hist_resp = requests.get(job_hist_url, headers=headers, verify=False)
                if job_hist_resp.status_code == 200:
                    get_execution_detail(job_hist_resp, headers, job_hist_url)
                break
        else:
            print("Unable to poll status of %s - Iteration %s " % (job_id, loop_ctr))
    if job_incomplete:
        print("Job %s incomplete after polling %s times...Check status" % (job_id, max_retries))

def get_execution_detail(job_hist_resp, headers, job_hist_url):
    """ Get execution details """
    job_history_id = str((job_hist_resp.json())['value'][0]['Id'])
    execution_hist_detail = "(" + job_history_id + ")/ExecutionHistoryDetails"
    job_hist_det_url = str(job_hist_url) + execution_hist_detail
    job_hist_det_resp = requests.get(job_hist_det_url,
                                     headers=headers,
                                     verify=False)
    if job_hist_det_resp.status_code == 200:
        print(job_hist_det_resp.text)
    else:
        print("Unable to parse job execution history .. Exiting")

def get_job(ip_address, header, job_id):
    """ Get Job details """
    url = 'https://{0}/api/JobService/Jobs({1})'.format(ip_address, job_id)
    pool = urllib3.HTTPSConnectionPool(ip_address, port=443, cert_reqs='CERT_NONE',
                                       assert_hostname=False)
    return pool.urlopen('GET', url, headers=header)


def get_baseline_id(ip_address, headers, id_repo, id_cat):
    """ Get Baseline id """
    url = 'https://%s/api/UpdateService/Baselines' % ip_address
    status, data = request(ip_address=ip_address, url=url, header=headers)
    if status == 200:
        if data["@odata.count"]:
            i = 0
            while i < len(data["value"]):
                repo_data = data["value"][i]["RepositoryId"]
                catalog_data = data["value"][i]["CatalogId"]
                if id_repo == repo_data and id_cat == catalog_data:
                    return id_repo, id_cat, data["value"][i]["Id"]
                if i == len(data["value"]):
                    print("unable to find  the corresponding baseline")
                    return 0
                i += 1
        else:
            return 0
    print("unable to get baseline id")
    return 0


def get_job_types(ip_address, header):
    """ Get job type """
    url = "https://{0}/api/JobService/JobTypes".format(ip_address)
    return request(ip_address=ip_address, url=url, header=header)


def request(ip_address, url, header, payload=None, method='GET'):
    """ Returns status and data """
    pool = urllib3.HTTPSConnectionPool(ip_address, port=443, cert_reqs='CERT_NONE',
                                       assert_hostname=False)
    request_obj = pool.urlopen(method, url, headers=header, body=json.dumps(payload))
    data = None
    if request_obj.data:
        data = json.loads(request_obj.data)
    return request_obj.status, data


def get_catalog_details(ip_address, headers):
    """ Get Catalog details """
    url = 'https://%s/api/UpdateService/Catalogs' % ip_address
    response = requests.get(url, headers=headers, verify=False)
    if response.status_code == 200:
        dev_response = response.json()
        if dev_response['@odata.count'] > 0:
            i = 0
            while i < len(dev_response["value"]):
                if dev_response["value"][i].get("Repository")["Source"] == "downloads.dell.com":
                    CATALOG_INFO["REPO_ID"] = dev_response["value"][i].get("Repository")["Id"]
                    CATALOG_INFO["CATALOG_ID"] = dev_response["value"][i]["Id"]
                    return CATALOG_INFO
                i += 1
        else:
            raise Exception("Not able to get Catalog details for baseline creation")
    else:
        print("unable to get catalog details")
        return 0


def get_group_details(ip_address, headers, group_id):
    """ Get  group details  from OME """
    device_url = 'https://%s/api/GroupService/Groups(%s)' % (ip_address, group_id)
    response = requests.get(device_url, headers=headers, verify=False)
    if response.status_code == 200:
        dev_response = response.json()
        if dev_response['Id'] == group_id:
            group_type = dev_response["TypeId"]
            group_name = dev_response["Name"]
            return group_type, group_name
        raise Exception("Unable to find group id")
    else:
        raise Exception("Unable to fetch group details")


def get_device_details(ip_address, headers, device_id):
    """ Get device details  from OME """
    device_url = 'https://%s/api/DeviceService/Devices(%s)' % (ip_address, device_id)
    response = requests.get(device_url, headers=headers, verify=False)
    if response.status_code == 200:
        dev_response = response.json()
        if dev_response['Id'] == device_id:
            device_type = dev_response["Type"]
            device_name = dev_response["DeviceName"]
            return device_type, device_name
        print("unable to find device id")
    else:
        print("Unable to fetch device details")
    return 0


def get_device_list(ip_address, headers):
    """ Get list of devices from OME """
    ome_device_list = None
    device_url = 'https://%s/api/DeviceService/Devices' % ip_address
    response = requests.get(device_url, headers=headers, verify=False)
    if response.status_code == 200:
        dev_response = response.json()
        if dev_response['@odata.count'] > 0:
            ome_device_list = [x['Id'] for x in dev_response['value']]
        else:
            print("No devices found at ", ip_address)
    else:
        print("No devices found at ", ip_address)
    return ome_device_list


def get_group_list(ip_address, headers):
    """ Get list of groups from OME """
    group_list = None
    group_url = 'https://%s/api/GroupService/Groups' % ip_address
    response = requests.get(group_url, headers=headers, verify=False)
    if response.status_code == 200:
        group_response = response.json()
        if group_response['@odata.count'] > 0:
            group_list = [x['Id'] for x in group_response['value']]
        else:
            print("No groups found at ", ip_address)
    else:
        print("No groups found at ", ip_address)
    return group_list


def catalog_creation_payload():
    """
    :return: dict representing the payload
    """
    return {
        "Filename": "",
        "SourcePath": "",
        "Repository": {
            "Name": 'Test' + time.strftime(":%Y:%m:%d-%H:%M:%S"),
            "Description": "Factory test",
            "RepositoryType": "DELL_ONLINE",
            "Source": "downloads.dell.com",
            "DomainName": "",
            "Username": "",
            "Password": "",
            "CheckCertificate": False
        }
    }


def baseline_creation_payload(id_cat, repository_id, target_id, target_type, target_name):
    """ Return payload for Baseline creation """
    return {
        "Name": "Factory Baseline" + time.strftime(":%Y:%m:%d-%H:%M:%S"),
        "Description": "Factory test1",
        "CatalogId": id_cat,
        "RepositoryId": repository_id,
        "DowngradeEnabled": True,
        "Is64Bit": True,
        "Targets": [
            {
                "Id": target_id,
                "Type": {
                    "Id": target_type,
                    "Name": target_name
                }
            }
        ]
    }


def create_payload_for_firmware_update(job_type_id, id_baseline,
                                       id_cat, repository_id, target_data):
    """ Formulate the payload to initiate a firmware update job """
    return {
        "JobName": "Update Firmware-Test:" + id_baseline,
        "JobDescription": "Firmware Update Job",
        "Schedule": "startNow",
        "State": "Enabled",
        "JobType": {
            "Id": job_type_id,
            "Name": "Update_Task"
        },
        "Params": [{
            "Key": "complianceReportId",
            "Value": id_baseline
        }, {
            "Key": "repositoryId",
            "Value": repository_id
        }, {
            "Key": "catalogId",
            "Value": id_cat
        }, {
            "Key": "operationName",
            "Value": "INSTALL_FIRMWARE"
        }, {
            "Key": "complianceUpdate",
            "Value": "true"
        }, {
            "Key": "signVerify",
            "Value": "true"
        }, {
            "Key": "stagingValue",
            "Value": "false"
        }],
        "Targets": target_data
    }


def catalog_deletion_payload(catalog_list):
    """  Returns payload to delete catalog """
    return {
        "CatalogIds": catalog_list
    }


def baseline_deletion_payload(baseline_list):
    """ Returns payload to delete baseline """
    return {
        "BaselineIds": baseline_list
    }


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    PARSER = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=RawTextHelpFormatter)
    PARSER.add_argument("--ip", required=True, help="OME Appliance IP")
    PARSER.add_argument("--user", required=True,
                        help="Username for OME Appliance",
                        default="admin")
    PARSER.add_argument("--password", required=True,
                        help="Password for OME Appliance")
    MUTEX_GROUP = PARSER.add_mutually_exclusive_group(required=True)
    MUTEX_GROUP.add_argument("--groupid", type=int,
                             help="Id of the group to update")
    MUTEX_GROUP.add_argument("--deviceid", type=int,
                             help="Id of the device to update")
    ARGS = PARSER.parse_args()
    IP_ADDRESS = ARGS.ip
    USER_NAME = ARGS.user
    PASSWORD = ARGS.password
    PARAM_MAP = {}
    TARGET_DATA = []
    try:
        AUTH_SUCCESS, HEADERS = authenticate_with_ome(IP_ADDRESS, USER_NAME,
                                                      PASSWORD)
        if AUTH_SUCCESS:
            if ARGS.groupid:
                GROUP_ID = ARGS.groupid
                PARAM_MAP['group_id'] = GROUP_ID
                PARAM_MAP['device_id'] = None
                GROUP_LIST = get_group_list(IP_ADDRESS, HEADERS)
                if GROUP_LIST:
                    if GROUP_ID in GROUP_LIST:
						group_url = "https://%s/api/GroupService/Groups(%s)/Devices"%(IP_ADDRESS,GROUP_ID)
						response = requests.get(group_url, headers=HEADERS, verify=False)
						if response.status_code == 200:
							dev_response = response.json()
							if dev_response['@odata.count'] == 0:
								raise Exception("There are no devices associated with this group id")
						else:
							raise Exception("Unable to fetch group device details")
                    else:
                        raise ValueError("Group %s not found on %s ... Exiting" % (
                            GROUP_ID, IP_ADDRESS))
            else:
                DEVICE_ID = ARGS.deviceid
                PARAM_MAP['device_id'] = DEVICE_ID
                PARAM_MAP['group_id'] = None
                DEVICE_LIST = get_device_list(IP_ADDRESS, HEADERS)
                if DEVICE_LIST:
                    if DEVICE_ID in DEVICE_LIST:
                        pass
                    else:
                        raise ValueError("Device %s not found on %s ... Exiting" % (
                            DEVICE_ID, IP_ADDRESS))
            CATALOG_DETAILS = check_for_existing_catalog(ip_address=IP_ADDRESS, headers=HEADERS)
            if CATALOG_DETAILS:
                for catalog in CATALOG_DETAILS:
                    if catalog["associated_baseline_id"]:
                        print("Existing catalog and baseline found from dell repo")
                        # Associated baselines exists, deleting baselines before catalogs
                        list1 = catalog.get("associated_baseline_id")
                        baseline_delete_status, baseline_delete_data = delete_baseline(
                            ip_address=IP_ADDRESS,
                            headers=HEADERS,
                            baseline_list=list1)
                        if baseline_delete_status == 204:
                            print("Successfully deleted the existing baseline")
                        else:
                            raise Exception("Unable to delete the existing baseline")
                        catalog_delete_status, catalog_delete_data = delete_catalog(
                            ip_address=IP_ADDRESS,
                            headers=HEADERS)
                        if catalog_delete_status == 204:
                            print("Successfully deleted the existing catalog")
                            CATALOGDETAILS = []
                        else:
                            raise Exception("Unable to delete the existing catalog")
                    else:
                        # when No Associated Baselines exists for catalog
                        print("Existing catalog found from dell repo")
                        catalog_delete_status, catalog_delete_data = delete_catalog(
                            ip_address=IP_ADDRESS,
                            headers=HEADERS)
                        if catalog_delete_status == 204:
                            print("Successfully deleted the existing catalog")
                            CATALOGDETAILS = []
                        else:
                            raise Exception("Unable to delete the existing catalog.!")
            CATALOG_ID = catalog_creation(ip_address=IP_ADDRESS, headers=HEADERS)
            if CATALOG_ID:
                print("Successfully created the catalog")
            else:
                raise Exception("Unable to create Catalog")
            REPO_ID, ID_CATALOG, BASELINE_ID = baseline_creation(ip_address=IP_ADDRESS,
                                                                 headers=HEADERS,
                                                                 param_map=PARAM_MAP)
            if BASELINE_ID == 0:
                raise Exception("Unable to create baseline")
            elif BASELINE_ID != 0:
                print("Successfully created baseline")
            COMPLIANCE_LIST = check_device_compliance_report(ip_address=IP_ADDRESS, headers=HEADERS,
                                                             id_baseline=BASELINE_ID)
            if COMPLIANCE_LIST:
                TARGET_PAYLOAD = create_target_payload(compliance_data_list=COMPLIANCE_LIST)
                if TARGET_PAYLOAD != 0:
                    firmware_update(ip_address=IP_ADDRESS, headers=HEADERS, repository_id=REPO_ID,
                                    id_cat=ID_CATALOG,
                                    id_baseline=BASELINE_ID, target_data=TARGET_PAYLOAD)
                else:
                    print("No component present for upgrade")
            else:
                print("No Target devices found to update the firmware")
        else:
            print("Unable to authenticate with OME .. Check IP/Username/Pwd")
    except OSError:
        print("Unexpected error:", sys.exc_info())
