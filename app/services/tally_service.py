"""
Tally Service Module
====================
Handles HTTP/XML communication with Tally Gateway Server.

TALLY GATEWAY:
-------------
Tally exposes a local HTTP server (default port 9000) that accepts:
- XML requests in TDL (Tally Definition Language) format
- Returns XML responses with requested data

CONNECTION:
----------
- URL: http://localhost:9000 (configurable in config.yaml)
- Method: POST
- Content-Type: text/xml
- Encoding: UTF-16 (Tally requirement)

REQUEST TYPES:
-------------
1. Export Data: Fetch records from Tally collections
2. Company Info: Get company details (GUID, AlterID, etc.)
3. Company List: Get all open companies

RESPONSE HANDLING:
-----------------
- Responses are UTF-16 encoded XML
- May have BOM (Byte Order Mark) - must be stripped
- Parse with ElementTree after encoding conversion

SVCURRENTCOMPANY:
----------------
- XML tag to specify target company
- If empty/missing: uses currently active company in Tally
- Must match exact company name in Tally

DEVELOPER NOTES:
---------------
- Always handle connection errors gracefully
- Retry logic for transient failures
- Check company is open in Tally before sync
- AlterID from company_info used for incremental sync detection
"""

import httpx
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

from ..config import config
from ..utils.logger import logger
from ..utils.decorators import retry, timed
from ..utils.helpers import parse_tally_date, parse_tally_amount, parse_tally_boolean


class TallyService:
    """Service for communicating with Tally via XML"""
    
    def __init__(self):
        self.server = config.tally.server
        self.port = config.tally.port
        self.base_url = f"http://{self.server}:{self.port}"
        self.timeout = config.health.tally_timeout
    
    @property
    def url(self) -> str:
        return self.base_url
    
    @retry(max_attempts=3, initial_delay=2.0, exceptions=(httpx.RequestError, httpx.TimeoutException))
    @timed
    async def send_xml(self, xml_request: str) -> str:
        """Send XML request to Tally and get response"""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Tally expects UTF-16 encoded XML
                response = await client.post(
                    self.base_url,
                    content=xml_request.encode('utf-16'),
                    headers={'Content-Type': 'text/xml; charset=utf-16'}
                )
                response.raise_for_status()
                
                # Try to decode response - Tally may return UTF-16 or UTF-8
                content = response.content
                try:
                    # Try UTF-16 first
                    return content.decode('utf-16')
                except UnicodeDecodeError:
                    try:
                        # Try UTF-16-LE (without BOM)
                        return content.decode('utf-16-le')
                    except UnicodeDecodeError:
                        try:
                            # Try UTF-8
                            return content.decode('utf-8')
                        except UnicodeDecodeError:
                            # Fallback to latin-1
                            return content.decode('latin-1')
        except httpx.RequestError as e:
            logger.error(f"Tally connection error: {e}")
            raise
        except Exception as e:
            logger.error(f"Tally request failed: {e}")
            raise
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to Tally and get company info"""
        xml_request = '''<?xml version="1.0" encoding="UTF-16"?>
        <ENVELOPE>
            <HEADER>
                <VERSION>1</VERSION>
                <TALLYREQUEST>Export</TALLYREQUEST>
                <TYPE>Data</TYPE>
                <ID>List of Companies</ID>
            </HEADER>
            <BODY>
                <DESC>
                    <STATICVARIABLES>
                        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                    </STATICVARIABLES>
                </DESC>
            </BODY>
        </ENVELOPE>'''
        
        try:
            response = await self.send_xml(xml_request)
            # Parse response to get company info
            return {
                "connected": True,
                "server": self.server,
                "port": self.port,
                "response_length": len(response)
            }
        except Exception as e:
            return {
                "connected": False,
                "server": self.server,
                "port": self.port,
                "error": str(e)
            }
    
    async def get_open_companies(self) -> List[Dict[str, Any]]:
        """Get list of all open companies in Tally"""
        xml_request = '''<?xml version="1.0" encoding="UTF-16"?>
        <ENVELOPE>
            <HEADER>
                <VERSION>1</VERSION>
                <TALLYREQUEST>Export</TALLYREQUEST>
                <TYPE>Data</TYPE>
                <ID>ListOfCompanies</ID>
            </HEADER>
            <BODY>
                <DESC>
                    <TDL>
                        <TDLMESSAGE>
                            <REPORT NAME="ListOfCompanies">
                                <FORMS>ListOfCompanies</FORMS>
                            </REPORT>
                            <FORM NAME="ListOfCompanies">
                                <PARTS>ListOfCompanies</PARTS>
                            </FORM>
                            <PART NAME="ListOfCompanies">
                                <LINES>ListOfCompanies</LINES>
                                <REPEAT>ListOfCompanies : Company</REPEAT>
                                <SCROLLED>Vertical</SCROLLED>
                            </PART>
                            <LINE NAME="ListOfCompanies">
                                <FIELDS>FldCompanyName,FldCompanyNumber,FldBooksFrom,FldBooksTo</FIELDS>
                            </LINE>
                            <FIELD NAME="FldCompanyName">
                                <SET>$Name</SET>
                            </FIELD>
                            <FIELD NAME="FldCompanyNumber">
                                <SET>$CompanyNumber</SET>
                            </FIELD>
                            <FIELD NAME="FldBooksFrom">
                                <SET>$BooksFrom</SET>
                            </FIELD>
                            <FIELD NAME="FldBooksTo">
                                <SET>$LastVoucherDate</SET>
                            </FIELD>
                        </TDLMESSAGE>
                    </TDL>
                </DESC>
            </BODY>
        </ENVELOPE>'''
        
        try:
            response = await self.send_xml(xml_request)
            return self._parse_company_list(response)
        except Exception as e:
            logger.error(f"Failed to get open companies: {e}")
            return []
    
    def _parse_company_list(self, xml_response: str) -> List[Dict[str, Any]]:
        """Parse company list from XML response"""
        companies = []
        try:
            # Remove BOM if present
            if xml_response.startswith('\ufeff'):
                xml_response = xml_response[1:]
            
            root = ET.fromstring(xml_response)
            
            # Find all company entries
            current_company = {}
            for elem in root.iter():
                if elem.tag == "FLDCOMPANYNAME" and elem.text:
                    if current_company:
                        companies.append(current_company)
                    current_company = {"name": elem.text, "number": "", "books_from": "", "books_to": ""}
                elif elem.tag == "FLDCOMPANYNUMBER" and current_company:
                    current_company["number"] = elem.text or ""
                elif elem.tag == "FLDBOOKSFROM" and current_company:
                    current_company["books_from"] = parse_tally_date(elem.text) or ""
                elif elem.tag == "FLDBOOKSTO" and current_company:
                    current_company["books_to"] = parse_tally_date(elem.text) or ""
            
            # Add last company
            if current_company and current_company.get("name"):
                companies.append(current_company)
            
            logger.info(f"Found {len(companies)} open companies in Tally")
            return companies
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return []
    
    async def get_company_info(self) -> Dict[str, Any]:
        """Get current company information from Tally"""
        xml_request = '''<?xml version="1.0" encoding="UTF-16"?>
        <ENVELOPE>
            <HEADER>
                <VERSION>1</VERSION>
                <TALLYREQUEST>Export</TALLYREQUEST>
                <TYPE>Data</TYPE>
                <ID>CurrentCompanyInfo</ID>
            </HEADER>
            <BODY>
                <DESC>
                    <TDL>
                        <TDLMESSAGE>
                            <REPORT NAME="CurrentCompanyInfo">
                                <FORMS>CurrentCompanyInfo</FORMS>
                            </REPORT>
                            <FORM NAME="CurrentCompanyInfo">
                                <PARTS>CurrentCompanyInfo</PARTS>
                            </FORM>
                            <PART NAME="CurrentCompanyInfo">
                                <LINES>CurrentCompanyInfo</LINES>
                                <REPEAT>CurrentCompanyInfo : Company</REPEAT>
                                <SCROLLED>Vertical</SCROLLED>
                            </PART>
                            <LINE NAME="CurrentCompanyInfo">
                                <FIELDS>FldCompanyName,FldBooksFrom,FldLastVoucherDate,FldGUID,FldAlterID</FIELDS>
                            </LINE>
                            <FIELD NAME="FldCompanyName">
                                <SET>$Name</SET>
                            </FIELD>
                            <FIELD NAME="FldBooksFrom">
                                <SET>$BooksFrom</SET>
                            </FIELD>
                            <FIELD NAME="FldLastVoucherDate">
                                <SET>$LastVoucherDate</SET>
                            </FIELD>
                            <FIELD NAME="FldGUID">
                                <SET>$GUID</SET>
                            </FIELD>
                            <FIELD NAME="FldAlterID">
                                <SET>$AlterID</SET>
                            </FIELD>
                        </TDLMESSAGE>
                    </TDL>
                </DESC>
            </BODY>
        </ENVELOPE>'''
        
        try:
            response = await self.send_xml(xml_request)
            return self._parse_company_info(response)
        except Exception as e:
            logger.error(f"Failed to get company info: {e}")
            return {"error": str(e)}
    
    def _parse_company_info(self, xml_response: str) -> Dict[str, Any]:
        """Parse company info from XML response"""
        try:
            # Remove BOM if present
            if xml_response.startswith('\ufeff'):
                xml_response = xml_response[1:]
            
            root = ET.fromstring(xml_response)
            
            company_name = ""
            books_from = ""
            last_voucher_date = ""
            guid = ""
            alterid = 0
            
            # Find company info fields
            for elem in root.iter():
                if elem.tag == "FLDCOMPANYNAME":
                    company_name = elem.text or ""
                elif elem.tag == "FLDBOOKSFROM":
                    books_from = parse_tally_date(elem.text) or ""
                elif elem.tag == "FLDLASTVOUCHERDATE":
                    last_voucher_date = parse_tally_date(elem.text) or ""
                elif elem.tag == "FLDGUID":
                    guid = elem.text or ""
                elif elem.tag == "FLDALTERID":
                    try:
                        alterid = int(elem.text or 0)
                    except:
                        alterid = 0
            
            return {
                "company_name": company_name,
                "books_from": books_from,
                "last_voucher_date": last_voucher_date,
                "guid": guid,
                "alterid": alterid
            }
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return {"error": f"XML parse error: {e}"}
    
    async def export_data(self, report_name: str, tdl_xml: str) -> str:
        """Export data from Tally using TDL XML"""
        xml_request = f'''<?xml version="1.0" encoding="UTF-16"?>
        <ENVELOPE>
            <HEADER>
                <VERSION>1</VERSION>
                <TALLYREQUEST>Export</TALLYREQUEST>
                <TYPE>Data</TYPE>
                <ID>{report_name}</ID>
            </HEADER>
            <BODY>
                <DESC>
                    <STATICVARIABLES>
                        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                        <SVCURRENTCOMPANY>{config.tally.company}</SVCURRENTCOMPANY>
                        <SVFROMDATE>{config.tally.from_date.replace('-', '')}</SVFROMDATE>
                        <SVTODATE>{config.tally.to_date.replace('-', '')}</SVTODATE>
                    </STATICVARIABLES>
                    <TDL>
                        <TDLMESSAGE>
                            {tdl_xml}
                        </TDLMESSAGE>
                    </TDL>
                </DESC>
            </BODY>
        </ENVELOPE>'''
        
        return await self.send_xml(xml_request)
    
    def parse_tabular_response(self, xml_response: str, field_names: List[str]) -> List[Dict[str, Any]]:
        """Parse tabular XML response into list of dictionaries"""
        rows = []
        try:
            # Remove BOM if present
            if xml_response.startswith('\ufeff'):
                xml_response = xml_response[1:]
            
            # Split by newlines and parse each row
            lines = xml_response.strip().split('\r\n')
            
            for line in lines:
                if not line.strip():
                    continue
                
                values = line.split('\t')
                if len(values) >= len(field_names):
                    row = {}
                    for i, field in enumerate(field_names):
                        value = values[i] if i < len(values) else ""
                        # Handle null marker
                        if value == "ñ":
                            value = None
                        row[field] = value
                    rows.append(row)
        except Exception as e:
            logger.error(f"Error parsing tabular response: {e}")
        
        return rows


    async def get_last_alter_ids(self) -> Dict[str, int]:
        """Get last AlterID for Master and Transaction from Tally"""
        xml_request = '''<?xml version="1.0" encoding="UTF-16"?>
        <ENVELOPE>
            <HEADER>
                <VERSION>1</VERSION>
                <TALLYREQUEST>Export</TALLYREQUEST>
                <TYPE>Data</TYPE>
                <ID>GetAlterIDs</ID>
            </HEADER>
            <BODY>
                <DESC>
                    <STATICVARIABLES>
                        <SVEXPORTFORMAT>ASCII (Comma Delimited)</SVEXPORTFORMAT>
                    </STATICVARIABLES>
                    <TDL>
                        <TDLMESSAGE>
                            <REPORT NAME="GetAlterIDs">
                                <FORMS>GetAlterIDs</FORMS>
                            </REPORT>
                            <FORM NAME="GetAlterIDs">
                                <PARTS>GetAlterIDs</PARTS>
                            </FORM>
                            <PART NAME="GetAlterIDs">
                                <LINES>GetAlterIDs</LINES>
                                <REPEAT>GetAlterIDs : MyCollection</REPEAT>
                                <SCROLLED>Vertical</SCROLLED>
                            </PART>
                            <LINE NAME="GetAlterIDs">
                                <FIELDS>FldAlterMaster,FldAlterTransaction</FIELDS>
                            </LINE>
                            <FIELD NAME="FldAlterMaster">
                                <SET>$AltMstId</SET>
                            </FIELD>
                            <FIELD NAME="FldAlterTransaction">
                                <SET>$AltVchId</SET>
                            </FIELD>
                            <COLLECTION NAME="MyCollection">
                                <TYPE>Company</TYPE>
                                <FILTER>FilterActiveCompany</FILTER>
                            </COLLECTION>
                            <SYSTEM TYPE="Formulae" NAME="FilterActiveCompany">$$IsEqual:##SVCurrentCompany:$Name</SYSTEM>
                        </TDLMESSAGE>
                    </TDL>
                </DESC>
            </BODY>
        </ENVELOPE>'''
        
        try:
            response = await self.send_xml(xml_request)
            # Parse CSV response: "master_id,transaction_id"
            response = response.strip().replace('"', '')
            if response:
                parts = response.split(',')
                if len(parts) >= 2:
                    master = int(parts[0]) if parts[0].isdigit() else 0
                    transaction = int(parts[1]) if parts[1].isdigit() else 0
                    return {"master": master, "transaction": transaction}
            return {"master": 0, "transaction": 0}
        except Exception as e:
            logger.error(f"Failed to get AlterIDs: {e}")
            return {"master": 0, "transaction": 0}


# Global service instance
tally_service = TallyService()
