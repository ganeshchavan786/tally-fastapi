"""
XML Builder Module
Generates TDL XML requests for Tally based on YAML config
Ported from Node.js tally.mjs generateXMLfromYAML function
"""

import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from html import escape as html_escape

from ..config import config
from ..utils.logger import logger


class XMLBuilder:
    """Builds TDL XML requests from YAML configuration"""
    
    def __init__(self):
        self.master_tables: List[Dict] = []
        self.transaction_tables: List[Dict] = []
        self._load_export_config()
    
    def _load_export_config(self) -> None:
        """Load export configuration from YAML file"""
        config_path = Path("tally-export-config.yaml")
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f)
                self.master_tables = yaml_config.get("master", [])
                self.transaction_tables = yaml_config.get("transaction", [])
                logger.info(f"Loaded {len(self.master_tables)} master tables, {len(self.transaction_tables)} transaction tables")
        else:
            logger.warning("tally-export-config.yaml not found")
    
    def get_all_tables(self) -> List[Dict]:
        """Get all table definitions"""
        return self.master_tables + self.transaction_tables
    
    def get_master_tables(self) -> List[Dict]:
        """Get master table definitions"""
        return self.master_tables
    
    def get_transaction_tables(self) -> List[Dict]:
        """Get transaction table definitions"""
        return self.transaction_tables
    
    def _format_number(self, num: int, template: str) -> str:
        """Format number with template like 'Fld00' -> 'Fld01'"""
        # Count zeros in template
        zeros = len(re.findall(r'0+$', template)[0]) if re.search(r'0+$', template) else 2
        prefix = re.sub(r'0+$', '', template)
        return f"{prefix}{str(num).zfill(zeros)}"
    
    def build_export_xml(self, table_config: Dict, from_date: str = "", to_date: str = "") -> str:
        """
        Build TDL XML for exporting a table
        Ported from Node.js generateXMLfromYAML function
        """
        collection_str = table_config.get("collection", "")
        fields = table_config.get("fields", [])
        fetch_list = table_config.get("fetch", [])
        filters = table_config.get("filters", [])
        
        # Get dates
        sv_from = from_date.replace("-", "") if from_date else config.tally.from_date.replace("-", "")
        sv_to = to_date.replace("-", "") if to_date else config.tally.to_date.replace("-", "")
        target_company = config.tally.company or ""
        
        # XML header
        retval = '<?xml version="1.0" encoding="utf-8"?><ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>TallyDatabaseLoaderReport</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>XML (Data Interchange)</SVEXPORTFORMAT>'
        retval += f'<SVFROMDATE>{sv_from}</SVFROMDATE><SVTODATE>{sv_to}</SVTODATE>'
        
        if target_company:
            retval += f'<SVCURRENTCOMPANY>{html_escape(target_company)}</SVCURRENTCOMPANY>'
        
        retval += '</STATICVARIABLES><TDL><TDLMESSAGE><REPORT NAME="TallyDatabaseLoaderReport"><FORMS>MyForm</FORMS></REPORT><FORM NAME="MyForm"><PARTS>MyPart01</PARTS></FORM>'
        
        # Push routes list - handle nested collections like "Voucher.AllLedgerEntries"
        lst_routes = collection_str.split(".")
        target_collection = lst_routes.pop(0)
        lst_routes.insert(0, "MyCollection")  # add basic collection level route
        
        # Loop through and append PART XML
        for i, route in enumerate(lst_routes):
            xml_part = self._format_number(i + 1, "MyPart00")
            xml_line = self._format_number(i + 1, "MyLine00")
            retval += f'<PART NAME="{xml_part}"><LINES>{xml_line}</LINES><REPEAT>{xml_line} : {route}</REPEAT><SCROLLED>Vertical</SCROLLED></PART>'
        
        # Loop through and append LINE XML (except last line which contains field data)
        for i in range(len(lst_routes) - 1):
            xml_line = self._format_number(i + 1, "MyLine00")
            xml_part = self._format_number(i + 2, "MyPart00")
            retval += f'<LINE NAME="{xml_line}"><FIELDS>FldBlank</FIELDS><EXPLODE>{xml_part}</EXPLODE></LINE>'
        
        # Last line with fields
        retval += f'<LINE NAME="{self._format_number(len(lst_routes), "MyLine00")}">'
        retval += '<FIELDS>'
        
        # Append field declaration list
        field_names = []
        for i in range(len(fields)):
            field_names.append(self._format_number(i + 1, "Fld00"))
        retval += ",".join(field_names)
        retval += '</FIELDS></LINE>'
        
        # Loop through each field
        for i, ifield in enumerate(fields):
            field_name = self._format_number(i + 1, "Fld00")
            field_xml = f'<FIELD NAME="{field_name}">'
            
            field_expr = ifield.get("field", "")
            field_type = ifield.get("type", "text")
            
            # Check if field is simple (just a field name) or complex expression
            is_simple = bool(re.match(r'^(\.\.)?[a-zA-Z0-9_]+$', field_expr))
            
            if is_simple:
                if field_type == "text":
                    field_xml += f'<SET>${field_expr}</SET>'
                elif field_type == "logical":
                    field_xml += f'<SET>if ${field_expr} then 1 else 0</SET>'
                elif field_type == "date":
                    field_xml += f'<SET>if $$IsEmpty:${field_expr} then $$StrByCharCode:241 else $$PyrlYYYYMMDDFormat:${field_expr}:"-"</SET>'
                elif field_type == "number":
                    field_xml += f'<SET>if $$IsEmpty:${field_expr} then "0" else $$String:${field_expr}</SET>'
                elif field_type == "amount":
                    field_xml += f'<SET>$$StringFindAndReplace:(if $$IsDebit:${field_expr} then -$$NumValue:${field_expr} else $$NumValue:${field_expr}):"(-)":"-"</SET>'
                elif field_type == "quantity":
                    field_xml += f'<SET>$$StringFindAndReplace:(if $$IsInwards:${field_expr} then $$Number:$$String:${field_expr}:"TailUnits" else -$$Number:$$String:${field_expr}:"TailUnits"):"(-)":"-"</SET>'
                elif field_type == "rate":
                    field_xml += f'<SET>if $$IsEmpty:${field_expr} then 0 else $$Number:${field_expr}</SET>'
                else:
                    field_xml += f'<SET>{field_expr}</SET>'
            else:
                # Complex expression - use as-is
                field_xml += f'<SET>{field_expr}</SET>'
            
            field_xml += f'<XMLTAG>{self._format_number(i + 1, "F00")}</XMLTAG>'
            field_xml += '</FIELD>'
            retval += field_xml
        
        # Blank field specification
        retval += '<FIELD NAME="FldBlank"><SET>""</SET></FIELD>'
        
        # Collection
        retval += f'<COLLECTION NAME="MyCollection"><TYPE>{target_collection}</TYPE>'
        
        # Fetch list
        if fetch_list:
            retval += f'<FETCH>{",".join(fetch_list)}</FETCH>'
        
        # Filters
        if filters:
            retval += '<FILTER>'
            filter_names = [self._format_number(j + 1, "Fltr00") for j in range(len(filters))]
            retval += ",".join(filter_names)
            retval += '</FILTER>'
        
        retval += '</COLLECTION>'
        
        # Filter definitions
        if filters:
            for j, flt in enumerate(filters):
                retval += f'<SYSTEM TYPE="Formulae" NAME="{self._format_number(j + 1, "Fltr00")}">{flt}</SYSTEM>'
        
        # XML footer
        retval += '</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>'
        
        return retval
    
    def build_company_info_xml(self) -> str:
        """Build XML to get company information"""
        return '''<?xml version="1.0" encoding="UTF-16"?>
        <ENVELOPE>
            <HEADER>
                <VERSION>1</VERSION>
                <TALLYREQUEST>Export</TALLYREQUEST>
                <TYPE>Data</TYPE>
                <ID>MyCompany</ID>
            </HEADER>
            <BODY>
                <DESC>
                    <STATICVARIABLES>
                        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                    </STATICVARIABLES>
                    <TDL>
                        <TDLMESSAGE>
                            <REPORT NAME="MyCompany">
                                <FORMS>MyCompany</FORMS>
                            </REPORT>
                            <FORM NAME="MyCompany">
                                <PARTS>MyCompany</PARTS>
                            </FORM>
                            <PART NAME="MyCompany">
                                <LINES>MyCompany</LINES>
                                <REPEAT>MyCompany : Company</REPEAT>
                                <SCROLLED>Vertical</SCROLLED>
                            </PART>
                            <LINE NAME="MyCompany">
                                <FIELDS>FldName,FldBooksFrom,FldLastVchDate</FIELDS>
                            </LINE>
                            <FIELD NAME="FldName"><SET>$Name</SET></FIELD>
                            <FIELD NAME="FldBooksFrom"><SET>$$PyrlYYYYMMDD:$BooksFrom</SET></FIELD>
                            <FIELD NAME="FldLastVchDate"><SET>$$PyrlYYYYMMDD:$LastVoucherDate</SET></FIELD>
                        </TDLMESSAGE>
                    </TDL>
                </DESC>
            </BODY>
        </ENVELOPE>'''


# Global instance
xml_builder = XMLBuilder()
