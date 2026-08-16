//+------------------------------------------------------------------+
//| ImportGoldMOfflineTicks.mq5                                      |
//| Offline-only, receipt-bound custom tick importer for GoldM.      |
//+------------------------------------------------------------------+
#property copyright "OpenAI"
#property link      "https://www.mql5.com"
#property version   "1.00"
#property script_show_inputs
#property strict

input string InpControlFile="";
input string InpExpectedControlSha256="";

#define MAX_CONTROL_BYTES 1048576
#define IMPORT_CHUNK_TICKS 250000
#define QUARANTINE_FROM_MSC 1772236800000
#define QUARANTINE_TO_MSC   1782864000000

struct ImportSession
  {
   ENUM_DAY_OF_WEEK day;
   uint             index;
   datetime         from_time;
   datetime         to_time;
  };

struct ImportControl
  {
   string import_id;
   string custom_symbol;
   string source_symbol;
   string custom_group;
   string description;
   string dataset_file;
   string raw_receipt_file;
   string dataset_sha256;
   string dataset_manifest_sha256;
   string symbol_spec_sha256;
   long   row_count;
   long   first_time_msc;
   long   last_time_msc;
   long   warmup_from_msc;
   long   run_from_msc;
   long   to_exclusive_msc;
   int    digits;
   ENUM_SYMBOL_CHART_MODE chart_mode;
   double point;
   double trade_tick_size;
   double trade_tick_value;
   double trade_tick_value_profit;
   double trade_tick_value_loss;
   double trade_contract_size;
   double volume_min;
   double volume_max;
   double volume_step;
   double volume_limit;
   ENUM_SYMBOL_CALC_MODE trade_calc_mode;
   ENUM_SYMBOL_TRADE_MODE trade_mode;
   ENUM_SYMBOL_TRADE_EXECUTION trade_execution_mode;
   int    trade_stops_level;
   int    trade_freeze_level;
   bool   spread_float;
   int    spread_points;
   int    order_mode;
   int    filling_mode;
   int    expiration_mode;
   ENUM_SYMBOL_SWAP_MODE swap_mode;
   double swap_long;
   double swap_short;
   string currency_base;
   string currency_profit;
   string currency_margin;
   string formula;
   ImportSession quote_sessions[];
   ImportSession trade_sessions[];
  };

string RequiredControlKeys[]=
  {
   "format","import_id","custom_symbol","source_symbol","custom_group",
   "description","dataset_file","raw_receipt_file","dataset_sha256",
   "dataset_manifest_sha256","symbol_spec_sha256","row_count",
   "first_time_msc","last_time_msc","warmup_from_msc","run_from_msc",
   "to_exclusive_msc","digits","chart_mode","point","trade_tick_size",
   "trade_tick_value","trade_tick_value_profit","trade_tick_value_loss",
   "trade_contract_size","volume_min","volume_max","volume_step",
   "volume_limit","trade_calc_mode","trade_mode","trade_execution_mode",
   "trade_stops_level","trade_freeze_level","spread_float","spread_points",
   "order_mode","filling_mode","expiration_mode","swap_mode","swap_long",
   "swap_short","currency_base","currency_profit","currency_margin","formula"
  };

bool SeenControlKeys[];

void Fail(const string message)
  {
   PrintFormat("GOLDM_OFFLINE_IMPORT_FAILED reason=%s error=%d",message,GetLastError());
  }

bool IsSafeRelativeFile(const string value)
  {
   if(StringLen(value)<2 || StringLen(value)>240 || StringFind(value,"..")>=0 ||
      StringFind(value,":")>=0 || StringGetCharacter(value,0)=='\\' ||
      StringGetCharacter(value,0)=='/')
      return(false);
   for(int i=0;i<StringLen(value);i++)
     {
      ushort ch=StringGetCharacter(value,i);
      bool allowed=(ch>='A' && ch<='Z') || (ch>='a' && ch<='z') ||
                   (ch>='0' && ch<='9') || ch=='.' || ch=='_' || ch=='-' ||
                   ch=='\\';
      if(!allowed)
         return(false);
     }
   return(true);
  }

bool IsToken(const string value,const int min_length,const int max_length)
  {
   int length=StringLen(value);
   if(length<min_length || length>max_length)
      return(false);
   for(int i=0;i<length;i++)
     {
      ushort ch=StringGetCharacter(value,i);
      bool allowed=(ch>='A' && ch<='Z') || (ch>='a' && ch<='z') ||
                   (ch>='0' && ch<='9') || ch=='.' || ch=='_' || ch=='-' || ch=='#';
      if(!allowed)
         return(false);
     }
   return(true);
  }

bool IsLowerSha256(const string value)
  {
   if(StringLen(value)!=64)
      return(false);
   for(int i=0;i<64;i++)
     {
      ushort ch=StringGetCharacter(value,i);
      if(!((ch>='0' && ch<='9') || (ch>='a' && ch<='f')))
         return(false);
     }
   return(true);
  }

bool IsCanonicalUnsigned(const string value)
  {
   int length=StringLen(value);
   if(length==0)
      return(false);
   if(length>1 && StringGetCharacter(value,0)=='0')
      return(false);
   for(int i=0;i<length;i++)
      if(StringGetCharacter(value,i)<'0' || StringGetCharacter(value,i)>'9')
         return(false);
   return(true);
  }

bool IsCanonicalNumber(const string value)
  {
   int length=StringLen(value);
   if(length==0)
      return(false);
   int i=0;
   if(StringGetCharacter(value,i)=='-')
     {
      i++;
      if(i>=length)
         return(false);
     }
   bool digits=false;
   bool dot=false;
   bool exponent=false;
   bool exponent_digits=false;
   for(;i<length;i++)
     {
      ushort ch=StringGetCharacter(value,i);
      if(ch>='0' && ch<='9')
        {
         if(exponent)
            exponent_digits=true;
         else
            digits=true;
         continue;
        }
      if(ch=='.' && !dot && !exponent && digits)
        {
         dot=true;
         continue;
        }
      if((ch=='e' || ch=='E') && !exponent && digits)
        {
         exponent=true;
         if(i+1<length && (StringGetCharacter(value,i+1)=='+' ||
                           StringGetCharacter(value,i+1)=='-'))
            i++;
         continue;
        }
      return(false);
     }
   return(digits && (!exponent || exponent_digits));
  }

string LowerPath(string value)
  {
   StringReplace(value,"/","\\");
   while(StringLen(value)>3 && StringGetCharacter(value,StringLen(value)-1)=='\\')
      value=StringSubstr(value,0,StringLen(value)-1);
   StringToLower(value);
   return(value);
  }

string BytesToHex(const uchar &bytes[])
  {
   string output="";
   for(int i=0;i<ArraySize(bytes);i++)
      output+=StringFormat("%02x",bytes[i]);
   return(output);
  }

bool FileSha256(const string file_name,string &sha256)
  {
   ResetLastError();
   int handle=FileOpen(file_name,FILE_READ|FILE_BIN);
   if(handle==INVALID_HANDLE)
      return(false);
   ulong size=FileSize(handle);
   if(size<1 || size>MAX_CONTROL_BYTES)
     {
      FileClose(handle);
      return(false);
     }
   uchar content[];
   if(ArrayResize(content,(int)size)!=(int)size ||
      FileReadArray(handle,content,0,(int)size)!=(uint)size)
     {
      FileClose(handle);
      return(false);
     }
   FileClose(handle);
   uchar key[];
   uchar digest[];
   ArrayResize(key,0);
   if(CryptEncode(CRYPT_HASH_SHA256,content,key,digest)!=32)
      return(false);
   sha256=BytesToHex(digest);
   return(IsLowerSha256(sha256));
  }

int KeyIndex(const string key)
  {
   for(int i=0;i<ArraySize(RequiredControlKeys);i++)
      if(RequiredControlKeys[i]==key)
         return(i);
   return(-1);
  }

bool ParseDay(const string value,ENUM_DAY_OF_WEEK &day)
  {
   if(value=="SUNDAY") day=SUNDAY;
   else if(value=="MONDAY") day=MONDAY;
   else if(value=="TUESDAY") day=TUESDAY;
   else if(value=="WEDNESDAY") day=WEDNESDAY;
   else if(value=="THURSDAY") day=THURSDAY;
   else if(value=="FRIDAY") day=FRIDAY;
   else if(value=="SATURDAY") day=SATURDAY;
   else return(false);
   return(true);
  }

bool AppendSession(ImportSession &sessions[],const string day_text,
                   const string index_text,const string from_text,const string to_text)
  {
   ENUM_DAY_OF_WEEK day;
   if(!ParseDay(day_text,day) || !IsCanonicalUnsigned(index_text) ||
      !IsCanonicalUnsigned(from_text) || !IsCanonicalUnsigned(to_text))
      return(false);
   long index=StringToInteger(index_text);
   long from_seconds=StringToInteger(from_text);
   long to_seconds=StringToInteger(to_text);
   if(index<0 || index>31 || from_seconds<0 || from_seconds>=to_seconds ||
      to_seconds>172800)
      return(false);
   int total=ArraySize(sessions);
   int expected=0;
   for(int i=0;i<total;i++)
      if(sessions[i].day==day)
         expected++;
   if(index!=expected || ArrayResize(sessions,total+1)!=total+1)
      return(false);
   sessions[total].day=day;
   sessions[total].index=(uint)index;
   sessions[total].from_time=(datetime)from_seconds;
   sessions[total].to_time=(datetime)to_seconds;
   return(true);
  }

bool AssignControlValue(ImportControl &control,const string key,const string value)
  {
   int index=KeyIndex(key);
   if(index<0 || SeenControlKeys[index])
      return(false);
   SeenControlKeys[index]=true;
   if(key=="format") return(value=="MT5_CUSTOM_TICK_IMPORT_CONTROL_V1");
   if(key=="import_id") control.import_id=value;
   else if(key=="custom_symbol") control.custom_symbol=value;
   else if(key=="source_symbol") control.source_symbol=value;
   else if(key=="custom_group") control.custom_group=value;
   else if(key=="description") control.description=value;
   else if(key=="dataset_file") control.dataset_file=value;
   else if(key=="raw_receipt_file") control.raw_receipt_file=value;
   else if(key=="dataset_sha256") control.dataset_sha256=value;
   else if(key=="dataset_manifest_sha256") control.dataset_manifest_sha256=value;
   else if(key=="symbol_spec_sha256") control.symbol_spec_sha256=value;
   else if(key=="row_count") control.row_count=StringToInteger(value);
   else if(key=="first_time_msc") control.first_time_msc=StringToInteger(value);
   else if(key=="last_time_msc") control.last_time_msc=StringToInteger(value);
   else if(key=="warmup_from_msc") control.warmup_from_msc=StringToInteger(value);
   else if(key=="run_from_msc") control.run_from_msc=StringToInteger(value);
   else if(key=="to_exclusive_msc") control.to_exclusive_msc=StringToInteger(value);
   else if(key=="digits") control.digits=(int)StringToInteger(value);
   else if(key=="chart_mode")
      control.chart_mode=(value=="BID" ? SYMBOL_CHART_MODE_BID : SYMBOL_CHART_MODE_LAST);
   else if(key=="point") control.point=StringToDouble(value);
   else if(key=="trade_tick_size") control.trade_tick_size=StringToDouble(value);
   else if(key=="trade_tick_value") control.trade_tick_value=StringToDouble(value);
   else if(key=="trade_tick_value_profit") control.trade_tick_value_profit=StringToDouble(value);
   else if(key=="trade_tick_value_loss") control.trade_tick_value_loss=StringToDouble(value);
   else if(key=="trade_contract_size") control.trade_contract_size=StringToDouble(value);
   else if(key=="volume_min") control.volume_min=StringToDouble(value);
   else if(key=="volume_max") control.volume_max=StringToDouble(value);
   else if(key=="volume_step") control.volume_step=StringToDouble(value);
   else if(key=="volume_limit") control.volume_limit=StringToDouble(value);
   else if(key=="trade_calc_mode") control.trade_calc_mode=(ENUM_SYMBOL_CALC_MODE)StringToInteger(value);
   else if(key=="trade_mode") control.trade_mode=(ENUM_SYMBOL_TRADE_MODE)StringToInteger(value);
   else if(key=="trade_execution_mode") control.trade_execution_mode=(ENUM_SYMBOL_TRADE_EXECUTION)StringToInteger(value);
   else if(key=="trade_stops_level") control.trade_stops_level=(int)StringToInteger(value);
   else if(key=="trade_freeze_level") control.trade_freeze_level=(int)StringToInteger(value);
   else if(key=="spread_float") control.spread_float=(value=="1");
   else if(key=="spread_points") control.spread_points=(int)StringToInteger(value);
   else if(key=="order_mode") control.order_mode=(int)StringToInteger(value);
   else if(key=="filling_mode") control.filling_mode=(int)StringToInteger(value);
   else if(key=="expiration_mode") control.expiration_mode=(int)StringToInteger(value);
   else if(key=="swap_mode") control.swap_mode=(ENUM_SYMBOL_SWAP_MODE)StringToInteger(value);
   else if(key=="swap_long") control.swap_long=StringToDouble(value);
   else if(key=="swap_short") control.swap_short=StringToDouble(value);
   else if(key=="currency_base") control.currency_base=value;
   else if(key=="currency_profit") control.currency_profit=value;
   else if(key=="currency_margin") control.currency_margin=value;
   else if(key=="formula") control.formula=value;
   else return(false);

   bool integer_key=(key=="row_count" || key=="first_time_msc" ||
                     key=="last_time_msc" || key=="warmup_from_msc" ||
                     key=="run_from_msc" || key=="to_exclusive_msc" ||
                     key=="digits" || key=="trade_calc_mode" || key=="trade_mode" ||
                     key=="trade_execution_mode" || key=="trade_stops_level" ||
                     key=="trade_freeze_level" || key=="spread_points" ||
                     key=="order_mode" || key=="filling_mode" ||
                     key=="expiration_mode" || key=="swap_mode");
   bool number_key=(key=="point" || key=="trade_tick_size" ||
                    key=="trade_tick_value" || key=="trade_tick_value_profit" ||
                    key=="trade_tick_value_loss" || key=="trade_contract_size" ||
                    key=="volume_min" || key=="volume_max" || key=="volume_step" ||
                    key=="volume_limit" || key=="swap_long" || key=="swap_short");
   if(integer_key && !IsCanonicalUnsigned(value)) return(false);
   if(number_key && !IsCanonicalNumber(value)) return(false);
   if(key=="spread_float" && value!="0" && value!="1") return(false);
   if(key=="chart_mode" && value!="BID" && value!="LAST") return(false);
   return(true);
  }

bool LoadControl(const string file_name,ImportControl &control)
  {
   ArrayResize(SeenControlKeys,ArraySize(RequiredControlKeys));
   ArrayInitialize(SeenControlKeys,false);
   int handle=FileOpen(file_name,FILE_READ|FILE_CSV|FILE_ANSI,';',CP_UTF8);
   if(handle==INVALID_HANDLE)
      return(false);
   string headers[5];
   for(int i=0;i<5;i++) headers[i]=FileReadString(handle);
   if(headers[0]!="record_type" || headers[1]!="key" || headers[2]!="value" ||
      headers[3]!="arg1" || headers[4]!="arg2" || !FileIsLineEnding(handle))
     {
      FileClose(handle);
      return(false);
     }
   while(!FileIsEnding(handle))
     {
      string record_type=FileReadString(handle);
      string key=FileReadString(handle);
      string value=FileReadString(handle);
      string arg1=FileReadString(handle);
      string arg2=FileReadString(handle);
      if(!FileIsLineEnding(handle) && !FileIsEnding(handle))
        {
         FileClose(handle);
         return(false);
        }
      if(record_type=="CONTROL")
        {
         if(arg1!="" || arg2!="" || !AssignControlValue(control,key,value))
           {
            FileClose(handle);
            return(false);
           }
        }
      else if(record_type=="QUOTE_SESSION")
        {
         if(!AppendSession(control.quote_sessions,key,value,arg1,arg2))
           {
            FileClose(handle);
            return(false);
           }
        }
      else if(record_type=="TRADE_SESSION")
        {
         if(!AppendSession(control.trade_sessions,key,value,arg1,arg2))
           {
            FileClose(handle);
            return(false);
           }
        }
      else
        {
         FileClose(handle);
         return(false);
        }
     }
   FileClose(handle);
   for(int i=0;i<ArraySize(SeenControlKeys);i++)
      if(!SeenControlKeys[i]) return(false);
   return(true);
  }

bool ValidateControl(const ImportControl &control)
  {
   if(!IsToken(control.import_id,8,96) || !IsToken(control.custom_symbol,2,31) ||
      !IsToken(control.source_symbol,2,31) ||
      LowerPath(control.custom_symbol)==LowerPath(control.source_symbol) ||
      !IsSafeRelativeFile(control.dataset_file) ||
      !IsSafeRelativeFile(control.raw_receipt_file) ||
      LowerPath(control.dataset_file)==LowerPath(control.raw_receipt_file) ||
      LowerPath(control.dataset_file)==LowerPath(InpControlFile) ||
      LowerPath(control.raw_receipt_file)==LowerPath(InpControlFile) ||
      !IsLowerSha256(control.dataset_sha256) ||
      !IsLowerSha256(control.dataset_manifest_sha256) ||
      !IsLowerSha256(control.symbol_spec_sha256))
      return(false);
   if(control.row_count<=0 || control.first_time_msc<0 ||
      control.first_time_msc>control.last_time_msc ||
      control.warmup_from_msc>control.first_time_msc ||
      control.run_from_msc<control.warmup_from_msc ||
      control.run_from_msc>=control.to_exclusive_msc ||
      control.last_time_msc>=control.to_exclusive_msc)
      return(false);
   if(control.warmup_from_msc<QUARANTINE_TO_MSC &&
      control.to_exclusive_msc>QUARANTINE_FROM_MSC)
      return(false);
   if(control.formula!="" || control.digits<0 || control.digits>12 ||
      control.point<=0 || control.trade_tick_size<=0 ||
      control.trade_tick_value<=0 || control.trade_tick_value_profit<=0 ||
      control.trade_tick_value_loss<=0 || control.trade_contract_size<=0 ||
      control.volume_min<=0 || control.volume_max<control.volume_min ||
      control.volume_step<=0 || control.volume_step>control.volume_max ||
      control.volume_limit<0 || control.trade_stops_level<0 ||
      control.trade_freeze_level<0 || control.spread_points<0 ||
      ArraySize(control.quote_sessions)==0 || ArraySize(control.trade_sessions)==0)
      return(false);
   return(true);
  }

bool SetInteger(const string symbol,const ENUM_SYMBOL_INFO_INTEGER property,const long value)
  {
   ResetLastError();
   return(CustomSymbolSetInteger(symbol,property,value) &&
          SymbolInfoInteger(symbol,property)==value);
  }

bool NearlyEqual(const double left,const double right)
  {
   double scale=MathMax(1.0,MathMax(MathAbs(left),MathAbs(right)));
   return(MathAbs(left-right)<=1.0e-12*scale);
  }

bool SetDouble(const string symbol,const ENUM_SYMBOL_INFO_DOUBLE property,const double value)
  {
   ResetLastError();
   return(CustomSymbolSetDouble(symbol,property,value) &&
          NearlyEqual(SymbolInfoDouble(symbol,property),value));
  }

bool SetString(const string symbol,const ENUM_SYMBOL_INFO_STRING property,const string value)
  {
   ResetLastError();
   return(CustomSymbolSetString(symbol,property,value) &&
          SymbolInfoString(symbol,property)==value);
  }

bool ConfigureSymbol(const ImportControl &control)
  {
   bool custom=false;
   if(SymbolExist(control.custom_symbol,custom))
     {
      if(!custom || !SymbolSelect(control.custom_symbol,false) ||
         !CustomSymbolDelete(control.custom_symbol))
         return(false);
     }
   ResetLastError();
   if(!CustomSymbolCreate(control.custom_symbol,control.custom_group,NULL))
      return(false);
   bool verified_custom=false;
   if(!SymbolExist(control.custom_symbol,verified_custom) || !verified_custom)
      return(false);
   bool ok=true;
   ok&=SetInteger(control.custom_symbol,SYMBOL_DIGITS,control.digits);
   ok&=SetInteger(control.custom_symbol,SYMBOL_CHART_MODE,control.chart_mode);
   ok&=SetInteger(control.custom_symbol,SYMBOL_TRADE_CALC_MODE,control.trade_calc_mode);
   ok&=SetInteger(control.custom_symbol,SYMBOL_TRADE_MODE,control.trade_mode);
   ok&=SetInteger(control.custom_symbol,SYMBOL_TRADE_EXEMODE,control.trade_execution_mode);
   ok&=SetInteger(control.custom_symbol,SYMBOL_TRADE_STOPS_LEVEL,control.trade_stops_level);
   ok&=SetInteger(control.custom_symbol,SYMBOL_TRADE_FREEZE_LEVEL,control.trade_freeze_level);
   ok&=SetInteger(control.custom_symbol,SYMBOL_SPREAD_FLOAT,control.spread_float ? 1 : 0);
   ok&=SetInteger(control.custom_symbol,SYMBOL_SPREAD,control.spread_points);
   ok&=SetInteger(control.custom_symbol,SYMBOL_ORDER_MODE,control.order_mode);
   ok&=SetInteger(control.custom_symbol,SYMBOL_FILLING_MODE,control.filling_mode);
   ok&=SetInteger(control.custom_symbol,SYMBOL_EXPIRATION_MODE,control.expiration_mode);
   ok&=SetInteger(control.custom_symbol,SYMBOL_SWAP_MODE,control.swap_mode);
   ok&=SetDouble(control.custom_symbol,SYMBOL_POINT,control.point);
   ok&=SetDouble(control.custom_symbol,SYMBOL_TRADE_TICK_SIZE,control.trade_tick_size);
   ok&=SetDouble(control.custom_symbol,SYMBOL_TRADE_TICK_VALUE,control.trade_tick_value);
   ok&=SetDouble(control.custom_symbol,SYMBOL_TRADE_TICK_VALUE_PROFIT,control.trade_tick_value_profit);
   ok&=SetDouble(control.custom_symbol,SYMBOL_TRADE_TICK_VALUE_LOSS,control.trade_tick_value_loss);
   ok&=SetDouble(control.custom_symbol,SYMBOL_TRADE_CONTRACT_SIZE,control.trade_contract_size);
   ok&=SetDouble(control.custom_symbol,SYMBOL_VOLUME_MIN,control.volume_min);
   ok&=SetDouble(control.custom_symbol,SYMBOL_VOLUME_MAX,control.volume_max);
   ok&=SetDouble(control.custom_symbol,SYMBOL_VOLUME_STEP,control.volume_step);
   ok&=SetDouble(control.custom_symbol,SYMBOL_VOLUME_LIMIT,control.volume_limit);
   ok&=SetDouble(control.custom_symbol,SYMBOL_SWAP_LONG,control.swap_long);
   ok&=SetDouble(control.custom_symbol,SYMBOL_SWAP_SHORT,control.swap_short);
   ok&=SetString(control.custom_symbol,SYMBOL_DESCRIPTION,control.description);
   ok&=SetString(control.custom_symbol,SYMBOL_CURRENCY_BASE,control.currency_base);
   ok&=SetString(control.custom_symbol,SYMBOL_CURRENCY_PROFIT,control.currency_profit);
   ok&=SetString(control.custom_symbol,SYMBOL_CURRENCY_MARGIN,control.currency_margin);
   ok&=SetString(control.custom_symbol,SYMBOL_FORMULA,"");
   if(!ok)
      return(false);
   for(int i=0;i<ArraySize(control.quote_sessions);i++)
     {
      ImportSession session=control.quote_sessions[i];
      if(!CustomSymbolSetSessionQuote(control.custom_symbol,session.day,session.index,
                                      session.from_time,session.to_time))
         return(false);
     }
   for(int i=0;i<ArraySize(control.trade_sessions);i++)
     {
      ImportSession session=control.trade_sessions[i];
      if(!CustomSymbolSetSessionTrade(control.custom_symbol,session.day,session.index,
                                      session.from_time,session.to_time))
         return(false);
     }
   return(VerifySessions(control));
  }

bool VerifySessions(const ImportControl &control)
  {
   for(int day=0;day<=6;day++)
     {
      uint quote_count=0;
      uint trade_count=0;
      datetime from_time,to_time;
      while(SymbolInfoSessionQuote(control.custom_symbol,(ENUM_DAY_OF_WEEK)day,
                                   quote_count,from_time,to_time))
        {
         bool matched=false;
         for(int i=0;i<ArraySize(control.quote_sessions);i++)
            if(control.quote_sessions[i].day==(ENUM_DAY_OF_WEEK)day &&
               control.quote_sessions[i].index==quote_count &&
               control.quote_sessions[i].from_time==from_time &&
               control.quote_sessions[i].to_time==to_time)
               matched=true;
         if(!matched) return(false);
         quote_count++;
        }
      while(SymbolInfoSessionTrade(control.custom_symbol,(ENUM_DAY_OF_WEEK)day,
                                   trade_count,from_time,to_time))
        {
         bool matched=false;
         for(int i=0;i<ArraySize(control.trade_sessions);i++)
            if(control.trade_sessions[i].day==(ENUM_DAY_OF_WEEK)day &&
               control.trade_sessions[i].index==trade_count &&
               control.trade_sessions[i].from_time==from_time &&
               control.trade_sessions[i].to_time==to_time)
               matched=true;
         if(!matched) return(false);
         trade_count++;
        }
      uint expected_quote=0;
      uint expected_trade=0;
      for(int i=0;i<ArraySize(control.quote_sessions);i++)
         if(control.quote_sessions[i].day==(ENUM_DAY_OF_WEEK)day) expected_quote++;
      for(int i=0;i<ArraySize(control.trade_sessions);i++)
         if(control.trade_sessions[i].day==(ENUM_DAY_OF_WEEK)day) expected_trade++;
      if(quote_count!=expected_quote || trade_count!=expected_trade) return(false);
     }
   return(true);
  }

bool ReadTickHeader(const int handle)
  {
   string expected[7]={"time_msc","bid","ask","last","volume","flags","volume_real"};
   for(int i=0;i<7;i++)
      if(FileReadString(handle)!=expected[i]) return(false);
   return(FileIsLineEnding(handle) || FileIsEnding(handle));
  }

bool ReadTick(const int handle,MqlTick &tick)
  {
   string values[7];
   for(int i=0;i<7;i++) values[i]=FileReadString(handle);
   if((!FileIsLineEnding(handle) && !FileIsEnding(handle)) ||
      !IsCanonicalUnsigned(values[0]) || !IsCanonicalNumber(values[1]) ||
      !IsCanonicalNumber(values[2]) || !IsCanonicalNumber(values[3]) ||
      !IsCanonicalUnsigned(values[4]) || !IsCanonicalUnsigned(values[5]) ||
      !IsCanonicalNumber(values[6]))
      return(false);
   tick.time_msc=StringToInteger(values[0]);
   tick.time=(datetime)(tick.time_msc/1000);
   tick.bid=StringToDouble(values[1]);
   tick.ask=StringToDouble(values[2]);
   tick.last=StringToDouble(values[3]);
   tick.volume=(ulong)StringToInteger(values[4]);
   tick.flags=(uint)StringToInteger(values[5]);
   tick.volume_real=StringToDouble(values[6]);
   return(tick.time_msc>=0 && tick.bid>0 && tick.ask>=tick.bid && tick.last>=0 &&
          tick.volume_real>=0 && MathIsValidNumber(tick.bid) &&
          MathIsValidNumber(tick.ask) && MathIsValidNumber(tick.last) &&
          MathIsValidNumber(tick.volume_real));
  }

bool FlushImportChunk(const string symbol,MqlTick &ticks[])
  {
   int total=ArraySize(ticks);
   if(total==0) return(true);
   ResetLastError();
   int replaced=CustomTicksReplace(symbol,ticks[0].time_msc,
                                   ticks[total-1].time_msc,ticks,total);
   if(replaced!=total) return(false);
   ArrayResize(ticks,0);
   return(true);
  }

bool ImportTicks(const ImportControl &control)
  {
   int handle=FileOpen(control.dataset_file,FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(handle==INVALID_HANDLE || !ReadTickHeader(handle))
     {
      if(handle!=INVALID_HANDLE) FileClose(handle);
      return(false);
     }
   MqlTick chunk[];
   long count=0;
   long previous=-1;
   long first_observed=-1;
   while(!FileIsEnding(handle))
     {
      MqlTick tick;
      if(!ReadTick(handle,tick) || tick.time_msc<previous ||
         tick.time_msc<control.warmup_from_msc ||
         tick.time_msc>=control.to_exclusive_msc)
        {
         FileClose(handle);
         return(false);
        }
      int total=ArraySize(chunk);
      if(total>=IMPORT_CHUNK_TICKS && tick.time_msc>previous)
        {
         if(!FlushImportChunk(control.custom_symbol,chunk))
           {
            FileClose(handle);
            return(false);
           }
         total=0;
        }
      if(total>=IMPORT_CHUNK_TICKS*4 && tick.time_msc==previous)
        {
         FileClose(handle);
         return(false);
        }
      if(ArrayResize(chunk,total+1,IMPORT_CHUNK_TICKS)!=total+1)
        {
         FileClose(handle);
         return(false);
        }
      chunk[total]=tick;
      if(count==0) first_observed=tick.time_msc;
      previous=tick.time_msc;
      count++;
     }
   FileClose(handle);
   if(!FlushImportChunk(control.custom_symbol,chunk)) return(false);
   return(count==control.row_count && first_observed==control.first_time_msc &&
          previous==control.last_time_msc);
  }

bool SameTick(const MqlTick &left,const MqlTick &right)
  {
   return(left.time_msc==right.time_msc && left.volume==right.volume &&
          left.flags==right.flags && NearlyEqual(left.bid,right.bid) &&
          NearlyEqual(left.ask,right.ask) && NearlyEqual(left.last,right.last) &&
          NearlyEqual(left.volume_real,right.volume_real));
  }

bool VerifyTicks(const ImportControl &control)
  {
   int handle=FileOpen(control.dataset_file,FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(handle==INVALID_HANDLE || !ReadTickHeader(handle))
     {
      if(handle!=INVALID_HANDLE) FileClose(handle);
      return(false);
     }
   long verified=0;
   long current_day=-1;
   MqlTick observed[];
   int observed_index=0;
   while(!FileIsEnding(handle))
     {
      MqlTick expected;
      if(!ReadTick(handle,expected))
        {
         FileClose(handle);
         return(false);
        }
      long day=expected.time_msc/86400000;
      if(day!=current_day)
        {
         if(current_day>=0 && observed_index!=ArraySize(observed))
           {
            FileClose(handle);
            return(false);
           }
         ulong from_msc=(ulong)(day*86400000);
         ulong to_msc=from_msc+86399999;
         ResetLastError();
         int copied=CopyTicksRange(control.custom_symbol,observed,COPY_TICKS_ALL,
                                   from_msc,to_msc);
         if(copied<=0)
           {
            FileClose(handle);
            return(false);
           }
         current_day=day;
         observed_index=0;
        }
      if(observed_index>=ArraySize(observed) || !SameTick(expected,observed[observed_index]))
        {
         FileClose(handle);
         return(false);
        }
      observed_index++;
      verified++;
     }
   FileClose(handle);
   return(verified==control.row_count && observed_index==ArraySize(observed));
  }

bool WriteReceipt(const ImportControl &control,const string control_sha256)
  {
   int handle=FileOpen(control.raw_receipt_file,
                       FILE_WRITE|FILE_CSV|FILE_ANSI,';',CP_UTF8);
   if(handle==INVALID_HANDLE) return(false);
   FileWrite(handle,"key","value");
   FileWrite(handle,"format","MT5_CUSTOM_TICK_IMPORT_RECEIPT_V1");
   FileWrite(handle,"status","VERIFIED_CACHE_MATCH");
   FileWrite(handle,"import_id",control.import_id);
   FileWrite(handle,"custom_symbol",control.custom_symbol);
   FileWrite(handle,"source_symbol",control.source_symbol);
   FileWrite(handle,"dataset_sha256",control.dataset_sha256);
   FileWrite(handle,"dataset_manifest_sha256",control.dataset_manifest_sha256);
   FileWrite(handle,"symbol_spec_sha256",control.symbol_spec_sha256);
   FileWrite(handle,"control_sha256",control_sha256);
   FileWrite(handle,"row_count",IntegerToString(control.row_count));
   FileWrite(handle,"first_time_msc",IntegerToString(control.first_time_msc));
   FileWrite(handle,"last_time_msc",IntegerToString(control.last_time_msc));
   FileWrite(handle,"formula","EMPTY");
   FileWrite(handle,"origin","NONE");
   FileWrite(handle,"portable","TRUE");
   FileWrite(handle,"connected","FALSE");
   FileFlush(handle);
   FileClose(handle);
   return(true);
  }

void OnStart()
  {
   if(MQLInfoInteger(MQL_TESTER) || TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      Fail("terminal must be offline and importer must not run in Strategy Tester");
      return;
     }
   if(LowerPath(TerminalInfoString(TERMINAL_PATH))!=
      LowerPath(TerminalInfoString(TERMINAL_DATA_PATH)))
     {
      Fail("terminal is not in portable mode");
      return;
     }
   if(!IsSafeRelativeFile(InpControlFile) || !IsLowerSha256(InpExpectedControlSha256))
     {
      Fail("invalid control-file inputs");
      return;
     }
   string observed_control_sha256="";
   if(!FileSha256(InpControlFile,observed_control_sha256) ||
      observed_control_sha256!=InpExpectedControlSha256)
     {
      Fail("control-file SHA-256 mismatch");
      return;
     }
   ImportControl control;
   if(!LoadControl(InpControlFile,control) || !ValidateControl(control))
     {
      Fail("control contract rejected");
      return;
     }
   if(FileIsExist(control.raw_receipt_file))
     {
      Fail("raw receipt already exists; replay and overwrite are prohibited");
      return;
     }
   if(!ConfigureSymbol(control))
     {
      Fail("custom-symbol configuration failed");
      return;
     }
   if(!ImportTicks(control))
     {
      Fail("tick import failed");
      return;
     }
   if(!VerifyTicks(control))
     {
      Fail("post-import cache comparison failed");
      return;
     }
   if(!WriteReceipt(control,observed_control_sha256))
     {
      Fail("receipt write failed");
      return;
     }
   PrintFormat("GOLDM_OFFLINE_IMPORT_VERIFIED importId=%s symbol=%s rows=%I64d first=%I64d last=%I64d controlSha256=%s datasetSha256=%s",
               control.import_id,control.custom_symbol,control.row_count,
               control.first_time_msc,control.last_time_msc,
               observed_control_sha256,control.dataset_sha256);
  }
