#property strict
#property service
#property version   "1.00"
#property description "Servico local somente leitura: exporta o calendario economico do MT5 para o ScalperLab."

input int InpRefreshSeconds = 60;
input int InpDaysBack = 2;
input int InpDaysForward = 7;

const string OUTPUT_FILE = "ScalperLab_calendar_v1.json";
const string TEMP_FILE = "ScalperLab_calendar_v1.tmp";

string JsonEscape(string value)
  {
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "\\r");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\t", "\\t");
   return value;
  }

string JsonNumber(const bool available, const double value)
  {
   if(!available || !MathIsValidNumber(value))
      return "null";
   return DoubleToString(value, 8);
  }

string ImportanceName(const ENUM_CALENDAR_EVENT_IMPORTANCE importance)
  {
   if(importance == CALENDAR_IMPORTANCE_HIGH) return "high";
   if(importance == CALENDAR_IMPORTANCE_MODERATE) return "moderate";
   if(importance == CALENDAR_IMPORTANCE_LOW) return "low";
   return "none";
  }

bool PublishCalendar()
  {
   datetime server_now = TimeTradeServer();
   datetime utc_now = TimeGMT();
   if(server_now <= 0 || utc_now <= 0)
      return false;

   MqlCalendarValue values[];
   datetime from = server_now - (datetime)MathMax(0, InpDaysBack) * 86400;
   datetime to = server_now + (datetime)MathMax(1, InpDaysForward) * 86400;
   ResetLastError();
   int count = CalendarValueHistory(values, from, to);
   int calendar_error = GetLastError();
   bool query_ok = (count >= 0 && calendar_error == 0);

   string json = "{\"schema\":1,\"provider\":\"MetaTrader 5 Economic Calendar\",\"status\":\"";
   json += query_ok ? "available" : "unavailable";
   json += "\",\"account_login\":" + IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN));
   json += ",\"account_server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\"";
   json += ",\"captured_at_epoch\":" + IntegerToString((long)utc_now);
   json += ",\"captured_at_utc\":\"" + TimeToString(utc_now, TIME_DATE|TIME_SECONDS) + "\"";
   json += ",\"trade_server_time\":\"" + TimeToString(server_now, TIME_DATE|TIME_SECONDS) + "\"";
   json += ",\"server_utc_offset_seconds\":" + IntegerToString((long)(server_now - utc_now));
   json += ",\"error_code\":" + IntegerToString(calendar_error) + ",\"events\":[";

   int written = 0;
   if(query_ok)
     {
      int total = (int)MathMin(count, 2000);
      for(int i = 0; i < total; i++)
        {
         MqlCalendarEvent event_info;
         if(!CalendarEventById(values[i].event_id, event_info))
            continue;
         MqlCalendarCountry country_info;
         string country = "";
         string currency = "";
         if(CalendarCountryById(event_info.country_id, country_info))
           {
            country = country_info.name;
            currency = country_info.currency;
           }

         if(written > 0)
            json += ",";
         json += "{\"event_id\":" + IntegerToString((long)values[i].event_id);
         json += ",\"value_id\":" + IntegerToString((long)values[i].id);
         json += ",\"name\":\"" + JsonEscape(event_info.name) + "\"";
         json += ",\"currency\":\"" + JsonEscape(currency) + "\"";
         json += ",\"country\":\"" + JsonEscape(country) + "\"";
         json += ",\"importance\":" + IntegerToString((int)event_info.importance);
         json += ",\"importance_name\":\"" + ImportanceName(event_info.importance) + "\"";
         json += ",\"event_time_server\":\"" + TimeToString(values[i].time, TIME_DATE|TIME_SECONDS) + "\"";
         json += ",\"seconds_from_capture\":" + IntegerToString((long)(values[i].time - server_now));
         json += ",\"actual\":" + JsonNumber(values[i].HasActualValue(), values[i].GetActualValue());
         json += ",\"forecast\":" + JsonNumber(values[i].HasForecastValue(), values[i].GetForecastValue());
         json += ",\"previous\":" + JsonNumber(values[i].HasPreviousValue(), values[i].GetPreviousValue());
         json += ",\"revised_previous\":" + JsonNumber(values[i].HasRevisedValue(), values[i].GetRevisedValue());
         json += ",\"impact_type\":" + IntegerToString((int)values[i].impact_type);
         json += ",\"source_url\":\"" + JsonEscape(event_info.source_url) + "\"}";
         written++;
        }
     }
   json += "]}";

   ResetLastError();
   int handle = FileOpen(TEMP_FILE, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON, 0, CP_UTF8);
   if(handle == INVALID_HANDLE)
     {
      PrintFormat("ScalperLab Calendar Service: falha ao abrir arquivo temporario (%d).", GetLastError());
      return false;
     }
   uint bytes = FileWriteString(handle, json);
   FileFlush(handle);
   FileClose(handle);
   if(bytes == 0)
     {
      FileDelete(TEMP_FILE, FILE_COMMON);
      Print("ScalperLab Calendar Service: exportacao vazia; snapshot anterior preservado.");
      return false;
     }
   ResetLastError();
   if(!FileMove(TEMP_FILE, FILE_COMMON, OUTPUT_FILE, FILE_COMMON|FILE_REWRITE))
     {
      PrintFormat("ScalperLab Calendar Service: falha ao publicar snapshot (%d).", GetLastError());
      FileDelete(TEMP_FILE, FILE_COMMON);
      return false;
     }
   PrintFormat("ScalperLab Calendar Service: %d evento(s), status %s.", written,
               query_ok ? "disponivel" : "indisponivel");
   return query_ok;
  }

void OnStart()
  {
   PrintFormat("ScalperLab Calendar: tipo=%s.",EnumToString((ENUM_PROGRAM_TYPE)MQLInfoInteger(MQL_PROGRAM_TYPE)));
   if(InpRefreshSeconds < 15 || InpDaysBack < 0 || InpDaysForward < 1 || InpDaysForward > 30)
     {
      Print("ScalperLab Calendar Service: parametros fora dos limites.");
      return;
     }
   int interval_ms = InpRefreshSeconds * 1000;
   while(!IsStopped())
     {
      PublishCalendar();
      int slept_ms = 0;
      while(!IsStopped() && slept_ms < interval_ms)
        {
         int slice_ms = (int)MathMin(1000, interval_ms - slept_ms);
         Sleep(slice_ms);
         slept_ms += slice_ms;
        }
     }
  }
