# -*- coding: utf-8 -*-
"""eCommerce_Recommenders_v1.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1BXnrmuwQb15Nzl46yeHVPUJp1pwn05tc
"""

### IMPORTS ###
import math
import os,sys
import findspark
import pandas as pd
import statistics as st
from typing import Any
from google.colab import drive
from pyspark.sql import SparkSession
from pyspark.sql.window import Window
from pyspark.sql.functions import col,collect_list,udf,avg,max,min,when,rank,lit
from pyspark.sql.types import IntegerType, StructType, StructField, StringType, FloatType

class ProductRecommender():
    user_id=[]
    topK=0
    duration=0
    purchase_thresholds=0
    view_thresholds=0
    catalog_path=""
    user_history_path=""
    category=""
    historical_data={}
    spark=None

    def __init__(self, id, dur, purchase_threshold, view_threshold, topk, category ,spark):
        self.user_id=id
        self.duration=dur
        self.purchase_thresholds=purchase_threshold
        self.view_thresholds=view_threshold
        self.topK=topk
        self.spark=spark
        self.category=category
        self.catalog_path="/content/drive/Shareddrives/FourYottaBytes_DA231o/eCommerce/compoundAnalysisResources/"
        self.user_history_path="/content/drive/Shareddrives/FourYottaBytes_DA231o/eCommerce/compoundAnalysisResources/"
        try:   
            if(dur<30):
                raise ValueError("Got duration less than 30. Please check and pass the value between [30, 190]")
            else:
                if self.category=="ALL":
                    self.catalog_path=self.catalog_path+"catalog_store/"+str(math.floor(dur/30))+"/"
                    self.user_history_path=self.user_history_path+"user_history_store/"+str(math.floor(dur/30))+"/"
                else:
                    self.catalog_path=self.catalog_path+"catalog_by_category_store/"+str(math.floor(dur/30))+"/main_category="+self.category+"/"
                    self.user_history_path=self.user_history_path+"user_history__by_category_store/"+str(math.floor(dur/30))+"/main_category="+self.category+"/"
                self.historical_data["catalog"]=spark.read.parquet(self.catalog_path)
                self.historical_data["user_history"]=spark.read.parquet(self.user_history_path)
        except ValueError as val_error:
            print('Caught this error: ' + repr(val_error))

    def get_recommendations_by_price(self):
        user_history_df=self.historical_data["user_history"].filter(col("user_id").isin(self.user_id))
        user_history_df.cache()
        
        purchase_user_history=user_history_df.filter(col("event_type")=="purchase").filter(col("event_count")>=self.purchase_thresholds)
        purchase_users=[r[0] for r in purchase_user_history.select("user_id").rdd.collect()]
        view_users=[item for item in self.user_id if item not in purchase_users]
        view_user_history=user_history_df.filter(col("user_id").isin(view_users)).filter(col("event_type")=="view").filter(col("event_count")>=self.view_thresholds)
        view_users=[r[0] for r in view_user_history.select("user_id").rdd.collect()]
        cold_start_users=[item for item in self.user_id if (item not in purchase_users and item not in view_users)]
        
        
        purchase_catalog=self.historical_data["catalog"].filter(col("event_type")=="purchase").drop("event_type")
        purchase_catalog.cache()

        user_action_df=purchase_user_history.select("user_id","event_type","event_count","avg_event_price","stddev","product_history").union(view_user_history.select("user_id","event_type","event_count","avg_event_price","stddev","product_history"))
        user_action_with_bounds_df=user_action_df.withColumn("sub_fac", when(col("stddev")<=20,40).otherwise(col("stddev")/2)).withColumn("lower_bound",col("avg_event_price")-col("sub_fac")).withColumn("upper_bound",col("avg_event_price")+col("sub_fac")).drop("sub_fac")
        user_bound_info=user_action_with_bounds_df.select("user_id","event_type","avg_event_price","stddev","product_history","lower_bound","upper_bound")
        user_prod_join=user_bound_info.join(purchase_catalog,[col("avg_price")>=col("lower_bound"), col("avg_price")<=col("upper_bound")]).filter('!array_contains(product_history, product_id)').drop("product_history")
        
        window = Window.partitionBy(col('user_id')).orderBy(col('event_count').desc())
   
        action_rec_df=user_prod_join.select('*', rank().over(window).alias('rank')).filter(col('rank') <= self.topK)

        """
            Used the window function and sorted the records within each user based on #sells
            Example:
            
              user 1 view 500 and 1000 (view price range that we created)
                  Before:

                  product_id      price   number of purchases
                  lg              550         6000  
                  apple           600         20000
                  samsung         900         10000

                  After:

                  product_id      price   number of purchases
                  apple           600         20000
                  samsung         900         10000
                  lg              550         6000  
                          
        """
        cold_start_rec=purchase_catalog.orderBy("event_count", ascending=False).select("product_id","category_code","brand","avg_price").limit(self.topK).withColumn("users",lit(str(cold_start_users)))

        user_history_df.unpersist()
        purchase_catalog.unpersist()
        
        return (action_rec_df,cold_start_rec)

    def get_top_sellers(self):
        return self.historical_data["catalog"].filter(col("event_type")=="purchase").drop("event_type").orderBy("event_count", ascending=False).select("product_id","category_code","brand","avg_price").limit(self.topK)

class XFactorBasedRecommendation():
  query_time = {"2020":["04", "03", "02", "01"], "2019":["12", "11", "10"]}


  def load_user_data(m):
    user_df_list = []
    for year, months in query_time.items():
      for month in months:
        load_path = "/content/drive/Shareddrives/FourYottaBytes_DA231o/eCommerce/PPA2/User_x_factor_"+year+"_"+month+".parquet"
        df_tmp = spark.read.parquet(load_path)
        user_df_list.append(df_tmp)
        m -= 1
        if m == 0:
          break
      if m == 0:
        break

    df_user_x = user_df_list[0]
    for i in range(1, m):
      df_user_x = df_user_x.union(user_df_list[i])

    return df_user_x

  def load_product_data(m):
    prod_df_list = []
    for year, months in query_time.items():
      for month in months:
        load_path = "/content/drive/Shareddrives/FourYottaBytes_DA231o/eCommerce/PPA2/Product_Bins_"+year+"_"+month+".parquet"
        df_tmp = spark.read.parquet(load_path)
        prod_df_list.append(df_tmp)
        m -= 1
        if m == 0:
          break
      if m == 0:
        break

    df_prod_b = prod_df_list[0]
    for i in range(1, m):
      df_prod_b = df_prod_b.union(prod_df_list[i])

    return df_prod_b

  def load_prod_db_user(m, bin, category):
    user_prod_list = []
    for year, months in query_time.items():
      for month in months:
        load_path = "/content/drive/Shareddrives/FourYottaBytes_DA231o/eCommerce/PPA2/Product_Bins_"+year+"_"+month+".parquet"+"/prime_cat="+category+"/Product_Bin="+str(bin)+"/*"
        df_tmp = spark.read.parquet(load_path)
        user_prod_list.append(df_tmp)
        m -= 1
        if m == 0:
          break
      if m == 0:
        break

    df_user_prod_b = user_prod_list[0]
    for i in range(1, m):
      df_user_prod_b = df_user_prod_b.union(user_prod_list[i])

    return df_user_prod_b

  def get_user_bin(x_factor):
    if x_factor == "NaN":
      return x_factor
    elif x_factor < -0.90:
      return 0
    elif x_factor < -0.75:
      return 1
    elif x_factor < -0.60:
      return 2
    elif x_factor < -0.45:
      return 3
    elif x_factor < -0.30:
      return 4
    elif x_factor < -0.15:
      return 5
    elif x_factor < 0.00:
      return 6
    elif x_factor < 0.15:
      return 7
    elif x_factor < 0.30:
      return 8
    elif x_factor < 0.45:
      return 9
    elif x_factor < 0.60:
      return 10
    elif x_factor < 0.75:
      return 11
    elif x_factor < 0.9:
      return 12
    else:
      return 13

  def query_PPA2(user_ids, category="None", months=7):
    # First load the data based on months
    df_user_dfx = load_user_data(months)
    df_user_dfx.show()
    #product_db = load_product_data(months)

    # Query user data for current users
    for user_id in user_ids:
      user_x_factor = df_user_dfx.filter(col("user_id") == user_id).groupBy("user_id").agg(avg("user_x_factor").alias("user_x_factor")).select("user_x_factor").collect()
      print(user_x_factor)
      if (user_x_factor == []):
        print("Cold Start User")
      else :
        # Using this x_factor, query the product database
        user_x_bin = get_user_bin(user_x_factor[0][0])
        user_prod_df = load_prod_db_user(months, user_x_bin, category)
        user_prod_df.show(10, False)

def setup_env(flag):
    if(flag):
        os.system("apt-get install openjdk-8-jdk-headless -qq > /dev/null")
        os.system("tar xf /content/drive/Shareddrives/FourYottaBytes_DA231o/spark-3.0.3-bin-hadoop2.7.tgz")
        os.system("pip install -q findspark")
    os.environ["JAVA_HOME"] = "/usr/lib/jvm/java-8-openjdk-amd64"
    os.environ["SPARK_HOME"] = "/content/spark-3.0.3-bin-hadoop2.7"
    findspark.init()
    findspark.find()
    drive.mount('/content/drive')
    spark = SparkSession.builder\
         .master("local[*]")\
         .appName("Colab")\
         .config('spark.ui.port', '4050')\
         .getOrCreate()
    return spark

def main():
    spark=Any
    setup_arg = sys.argv[1:][0]
    if setup_arg=="setup":
        spark=setup_env(True)
    else:
        spark=setup_env(False)
    print("This is the Homepage Recommendation Script:")
    h_obj = Homepage(
        id=[
            "512389317",
            "513696407",
            "514688413",
            "494701812",
            "512571292",
            "coldster1",
            "coldster2",
            "628167977",
        ],
        dur=60,
        purchase_threshold=8,
        view_threshold=7000,
        topk=4,
        spark=spark
    )
    #TODO: TOP CATEGORIES FOR THE USER BASED ON HIS ACTIVITY ON HOMEPAGE (RANK THE CATEGORIES: EX: TOP 4 CATEGORIES) (purchased/per thousand views ?)
    recs = h_obj.get_recommendations_by_price()
    recs[0].show(100, 0)
    recs[1].show(100, 0)

    c_obj = CategoryPage(
        id=[
            "512389317",
            "513696407",
            "514688413",
            "494701812",
            "512571292",
            "coldster1",
            "coldster2",
            "628167977",
        ],
        dur=60,
        purchase_threshold=8,
        view_threshold=700,
        topk=4,
        category="electronics",
        spark=spark
    )
    recs = c_obj.get_recommendations_by_price()
    recs[0].show(100, 0)
    recs[1].show(100, 0)


if __name__ == "__main__":
    main()

